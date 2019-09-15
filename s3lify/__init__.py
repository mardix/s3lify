
import re
import yaml
import time
import boto3
import botocore
import json
import os
import threading
import uuid
import tempfile
import mimetypes
import tldextract

NAME = "S3lify"
CWD = os.getcwd()

MANIFEST_FILE = ".s3lify.manifest"

MIMETYPE_MAP = {
    '.js':   'application/javascript',
    '.mov':  'video/quicktime',
    '.mp4':  'video/mp4',
    '.m4v':  'video/x-m4v',
    '.3gp':  'video/3gpp',
    '.woff': 'application/font-woff',
    '.woff2': 'font/woff2',
    '.eot':  'application/vnd.ms-fontobject',
    '.ttf':  'application/x-font-truetype',
    '.otf':  'application/x-font-opentype',
    '.svg':  'image/svg+xml',
}
MIMETYPE_DEFAULT = 'application/octet-stream'

CLOUDFRONT_ZONE_ID = 'Z2FDTNDATAQYW2'

S3_HOSTED_ZONE_IDS = {
    'us-east-1': 'Z3AQBSTGFYJSTF',
    'us-west-1': 'Z2F56UZL2M1ACD',
    'us-west-2': 'Z3BJ6K6RIION7M',
    'ap-south-1': 'Z11RGJOFQNVJUP',
    'ap-northeast-1': 'Z2M4EHUR26P7ZW',
    'ap-northeast-2': 'Z3W03O7B5YMIYP',
    'ap-southeast-1': 'Z3O0J2DXBE1FTB',
    'ap-southeast-2': 'Z1WCIGYICN2BYD',
    'eu-central-1': 'Z21DNDUVLTQW6Q',
    'eu-west-1': 'Z1BKCTXD74EZPE',
    'sa-east-1': 'Z7KQH4QJS55SO',
    'us-gov-west-1': 'Z31GFT0UA1I2HV',
}


def get_mimetype(filename):
    mimetype, _ = mimetypes.guess_type(filename)
    if mimetype:
        return mimetype
    base, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext in MIMETYPE_MAP:
        return MIMETYPE_MAP[ext]
    return MIMETYPE_DEFAULT


def chunk_list(items, size):
    """
    Return a list of chunks
    :param items: List
    :param size: int The number of items per chunk
    :return: List
    """
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def extract_domain(url):
    d = tldextract.extract(url)
    return '.'.join([d.domain, d.suffix])

def caller_reference_uuid():
    return str(uuid.uuid4())

class S3lify(object):
    """
    To manage S3 website and domain on Route53
    """

    def __init__(self,
                 domain,
                 region="us-east-1",
                 aws_access_key_id=None,
                 aws_secret_access_key=None,
                 **kwargs):
        """

        :param domain: the website name to create, without WWW.
        :param region: the region of the site
        :param access_key_id: AWS
        :param secret_access_key: AWS
        :param setup_dns: bool - If True it will create route53
        :param allow_www: Bool - If true, it will create a second bucket with www.
        """

        # This will be used to pass to concurrent upload
        self.aws_params = {
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "region_name": region
        }
        self.region = region

        self._s3 = boto3.client('s3', **self.aws_params)
        self._route53 = boto3.client('route53', **self.aws_params)
        self._cloudfront = boto3.client('cloudfront', **self.aws_params)
        self._acm = boto3.client('acm', **self.aws_params)
        self._route53domains = boto3.client('route53domains', **self.aws_params)

        self.domain = domain
        self.tld_domain = extract_domain(self.domain)
        self.set_www = self.domain == self.tld_domain
        self.s3_bucket = domain
        self.s3_bucket_www = "www." + self.domain

        self.www_domain = "www." + self.domain
        self.s3_domain = "%s.s3-website-%s.amazonaws.com" % (self.domain, region)
        self.s3_url = "http://" + self.s3_domain
        self.domain_url = "http://" + self.domain

    @property
    def site_exists(self):
        return self.s3_get_bucket_status(self.domain)[0]

    @property
    def has_hosted_zone(self):
        return self._route53_get_hosted_zone_id() is not None

    @property
    def has_certificate(self):
        return self._acm_get_certificate_arn() is not None

    @property
    def has_distribution_id():
        return self.cloudfront_get_distribution_id() is not None

# Route 53

    def _route53_get_hosted_zone(self):
        hosted_zone = self._route53.list_hosted_zones()
        if hosted_zone or "HostedZones" in hosted_zone:
            for hz in hosted_zone["HostedZones"]:
                if hz["Name"].rstrip(".") == self.tld_domain:
                    return hz

    def _route53_get_hosted_zone_id(self):
        hosted_zone = self._route53_get_hosted_zone()
        if hosted_zone:
            return hosted_zone["Id"]

    def route53_create_hosted_zone(self):
        hosted_zone = self._route53_get_hosted_zone()
        if hosted_zone:
            return hosted_zone

        response = self._route53.create_hosted_zone(
            Name=self.tld_domain,
            CallerReference=caller_reference_uuid(),
            HostedZoneConfig={
                'Comment': "HostedZone created by S3lify.py!",
                'PrivateZone': False
            })
        return response['HostedZone']

    def route53_set_cname(self, name, value):
        hosted_zone = self.route53_create_hosted_zone()
        record = {
            "Changes": [{
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": name,
                    "Type": "CNAME",
                    "TTL": 30,
                    "ResourceRecords": [{
                        "Value": value
                    }]
                }
            }]
        }
        response = self._route53.change_resource_record_sets(
            HostedZoneId=hosted_zone["Id"],
            ChangeBatch=record)
        return True if response and "ChangeInfo" in response else False

    def route53_get_ns_values(self):
        """
        Return a list of NS values to put in the registrar
        :return list:
        """
        hosted_zone_id = self._route53_get_hosted_zone_id()
        if hosted_zone_id:
            rrset = self._route53.list_resource_record_sets(HostedZoneId=hosted_zone_id)
            for s in rrset["ResourceRecordSets"]:
                if s["Type"] == 'NS':
                    return [r["Value"] for r in s["ResourceRecords"]]
                

    def route53domains_update_dns(self):
        """
        If using route53domains as the registrar, it will update 
        the registrar DNS to reflect the route 53 values.
        """
        try:
            nameservers = self.route53_get_ns_values()
            nameservers2 = [n.rstrip('.') for n in self.route53_get_ns_values()]

            rdomain = self._route53domains.get_domain_detail(DomainName=self.tld_domain)
            rdNS = [d["Name"].rstrip('.') for d in rdomain["Nameservers"]]

            # The name servers don't match, attempt to update it.
            if bool(set(nameservers2) & set(rdNS)) is False:
                Nameservers = [{"Name": k} for k in self.route53_get_ns_values()]
                response = self._route53domains.update_domain_nameservers(
                    DomainName=self.tld_domain,
                    Nameservers=Nameservers
                )
                if response and response["OperationId"]:
                    return True

        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ["InvalidInput"]:
                return False, 404, e.response["Error"]["Message"]
            return False

    def _route53_update_a_records(self, dns_name, zone_id=None):
        hosted_zone = self.route53_create_hosted_zone()
        change_batch_payload = {
            'Changes': [
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': self.domain,
                        'Type': 'A',
                        'AliasTarget': {
                            'HostedZoneId': zone_id or S3_HOSTED_ZONE_IDS[self.region],
                            'DNSName': dns_name,
                            'EvaluateTargetHealth': False
                        }
                    }
                }
            ]
        }

        # With WWW
        if self.set_www:
            change_batch_payload["Changes"].append({
                'Action': 'UPSERT',
                'ResourceRecordSet': {
                    'Name': self.www_domain,
                    'Type': 'A',
                    'AliasTarget': {
                            'HostedZoneId': zone_id or S3_HOSTED_ZONE_IDS[self.region],
                            'DNSName': dns_name,
                            'EvaluateTargetHealth': False
                    }
                }
            })

        response = self._route53.change_resource_record_sets(
            HostedZoneId=hosted_zone["Id"],
            ChangeBatch=change_batch_payload)
        return True if response and "ChangeInfo" in response else False

# Cloudfront

    def cloudfront_create_distribution(self):
        """
        To create a distribution in cloudfront
        """
        # Automatically pick the distribution_id
        distribution_id = self.cloudfront_get_distribution_id()
        if not distribution_id:
            arn = self._acm_get_certificate_arn()
            if arn:
                dist_config = _make_cloudfront_config(domain_name=self.domain, ssl_arn=arn, s3_domain=self.s3_domain)
                res = self._cloudfront.create_distribution(DistributionConfig=dist_config)
                return res

    def cloudfront_update_route53_a_records(self):
        """
        Update the A records with the cloudfront domain, so it can use the SSL
        """
        domain = self.cloudfront_get_distribution_domain_name()
        if domain:
            self._route53_update_a_records(domain, CLOUDFRONT_ZONE_ID)

    def cloudfront_get_distribution_id(self):
        distribution_id = None
        dists = self._cloudfront.list_distributions()
        items = dists['DistributionList']["Items"]
        for item in items:
            for i in item["Origins"]["Items"]:
                if self.s3_domain == i['DomainName']:
                    return item['Id']

    def cloudfront_get_distribution_domain_name(self):
        distribution_id = None
        dists = self._cloudfront.list_distributions()
        items = dists['DistributionList']["Items"]
        for item in items:
            for i in item["Origins"]["Items"]:
                if self.s3_domain == i['DomainName']:
                    return item['DomainName']

    def cloudfront_invalidate_objects(self):
        distribution_id = self.cloudfront_get_distribution_id()
        if distribution_id:
            response = self._cloudfront.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': 1,
                        'Items': [
                            '/*',
                        ]
                    },
                    'CallerReference': caller_reference_uuid()
                }
            )
# ACM

    def acm_generate_certificate(self):
        """
        Generate an ACM certificate
        """
        SubjectAlternativeNames = [
            "*.%s" % self.domain
        ]
        arn = self._acm_get_certificate_arn()
        if not arn:
            resp = self._acm.request_certificate(
                DomainName=self.domain,
                # SubjectAlternativeNames=SubjectAlternativeNames,
                ValidationMethod='DNS')
            # Pause to allow the generation of the certificate
            time.sleep(2)
            if resp:
                return True

    def acm_update_route53_cname_records(self):
        """
        Update the CNAME, to validate Amazon certificate with DNS
        """
        r = self._acm_get_certificate_cname_config()
        if r and r[0] is True and r[1] and r[2]:
            self.route53_set_cname(r[1], r[2])
            return True

    def acm_get_certificate_status(self):
        arn = self._acm_get_certificate_arn()
        if arn:
            cert = self._acm.describe_certificate(CertificateArn=arn)
            if cert and cert["Certificate"]:
                return cert["Certificate"]["Status"]

    def _acm_get_certificate_arn(self):
        resp = self._acm.list_certificates()
        for c in resp["CertificateSummaryList"]:
            if self.domain == c["DomainName"]:
                return c["CertificateArn"]

    def _acm_get_certificate_cname_config(self):
        arn = self._acm_get_certificate_arn()
        if arn:
            cert = self._acm.describe_certificate(CertificateArn=arn)
            if cert and cert["Certificate"]:
                for domainValidations in cert["Certificate"]["DomainValidationOptions"]:
                    if domainValidations["ValidationStatus"] == "PENDING_VALIDATION" \
                            and domainValidations["ValidationMethod"] == "DNS":
                        cname_name = domainValidations["ResourceRecord"]["Name"]
                        cname_value = domainValidations["ResourceRecord"]["Value"]
                        return True, cname_name, cname_value
                    if domainValidations["ValidationStatus"] == "ISSUED":
                        return True, None, None


# S3


    def s3_create_site(self, index_file="index.html", error_file="error.html"):
        """
        Setup the site in S3
        """
        exists, error_code, error_message = self.s3_get_bucket_status(self.s3_bucket)
        if not exists:
            if error_code == "404":
                # Allow read access
                policy_payload = {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Sid": "Allow Public Access to All Objects",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": "s3:GetObject",
                        "Resource": "arn:aws:s3:::%s/*" % (self.domain)
                    }
                    ]
                }
                # Make bucket website and add index.html and error.html
                website_payload = {
                    'ErrorDocument': {
                        'Key': error_file
                    },
                    'IndexDocument': {
                        'Suffix': index_file
                    }
                }
                self._s3.create_bucket(Bucket=self.s3_bucket)
                self._s3.put_bucket_policy(Bucket=self.s3_bucket, Policy=json.dumps(policy_payload))
                self._s3.put_bucket_website(Bucket=self.s3_bucket, WebsiteConfiguration=website_payload)

                # Enable WWW to redirect to non-www
                # It will create www bucket
                if self.set_www:
                    redirect_payload = {
                        'RedirectAllRequestsTo': {
                            'HostName': self.domain,
                            'Protocol': 'https'
                        }
                    }
                    self._s3.create_bucket(Bucket=self.s3_bucket_www)
                    self._s3.put_bucket_website(Bucket=self.s3_bucket_www, WebsiteConfiguration=redirect_payload)
                return True
            else:
                raise Exception("Can't create website's bucket '%s' on AWS S3. "
                                "Error: %s" % (self.domain, error_message))
        return exists

    def s3_upload(self, build_dir):
        """
        Upload a site directory to S3
        :param build_dir: The directory to upload
        :return:
        """
        files_list = []
        for root, dirs, files in os.walk(build_dir):
            for filename in files:
                local_path = os.path.join(root, filename)
                s3_path = os.path.relpath(local_path, build_dir)
                mimetype = get_mimetype(local_path)

                kwargs = dict(aws_params=self.aws_params,
                              bucket_name=self.domain,
                              local_path=local_path,
                              s3_path=s3_path,
                              mimetype=mimetype)

                files_list.append(s3_path)
                threading.Thread(target=_s3_upload_file, kwargs=kwargs)\
                    .start()

        # Save the files that have been uploaded
        self._s3_update_manifest(files_list)

    def s3_update_route53_a_records(self):
        dns_name = "s3-website-%s.amazonaws.com" % self.region
        return self._route53_update_a_records(dns_name)

    def s3_get_bucket_status(self, name):
        """
        Get the bucket status
        :param name:
        :return: tuple (exists, error_code, error_message)
        """
        try:
            self._s3.head_bucket(Bucket=name)
            info = self._s3.get_bucket_website(Bucket=name)
            if not info:
                return False, 404, "Configure improrperly"
            return True, None, None
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ["403", "404"]:
                return False, e.response["Error"]["Code"], e.response["Error"]["Message"]
            else:
                raise e

    def s3_purge_files(self, exclude_files=["index.html", "error.html"]):
        """
        To delete files that are in the manifest
        :param excludes_files: list : files to not delete
        :return:
        """
        for chunk in chunk_list(self._s3_get_manifest(), 1000):
            try:
                self._s3.delete_objects(
                    Bucket=self.s3_bucket,
                    Delete={
                        'Objects': [{"Key": f} for f in chunk
                                    if f not in exclude_files]
                    }
                )
            except Exception as ex:
                pass

    def s3_create_manifest(self):
        """
        To create a manifest db for the current
        :return:
        """
        obj = self._s3.list_objects_v2(Bucket=self.s3_bucket)
        if 'Contents' in obj:
            for k in obj['Contents']:
                key = k["Key"]
                files = []
                if key not in [MANIFEST_FILE]:
                    files.append(key)
                self._s3_update_manifest(files)

    def _s3_update_manifest(self, files_list):
        """
        Write manifest files
        :param files_list: list
        :return:
        """
        if files_list:
            data = ",".join(files_list)
            self._s3.put_object(Bucket=self.s3_bucket,
                                Key=MANIFEST_FILE,
                                Body=data,
                                ACL='private')

    def _s3_get_manifest(self):
        """
        Return the list of items in the manifest
        :return: list
        """
        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            try:
                self._s3.download_fileobj(self.domain, MANIFEST_FILE, tmp)
                tmp.seek(0)
                data = tmp.read()
                if data is not None:
                    return data.split(",")
            except Exception as ex:
                pass
        return []


def _s3_upload_file(aws_params, bucket_name, local_path, s3_path, mimetype):
    """
    Upload a file to S3. Used mainly with threading
    """
    s3 = boto3.client("s3", **aws_params)
    s3.upload_file(local_path,
                   Bucket=bucket_name,
                   Key=s3_path,
                   ExtraArgs={"ContentType": mimetype})


def _make_cloudfront_config(domain_name, s3_domain, ssl_arn):
    id = "S3-website-%s" % s3_domain
    return {
        'CallerReference': caller_reference_uuid(),
        'Aliases': {'Quantity': 1, 'Items': [domain_name]},
        'Origins': {
            'Quantity': 1,
            'Items': [
                {
                    'Id': id,
                    'DomainName': s3_domain,
                    'OriginPath': '',
                    'CustomHeaders': {'Quantity': 0, 'Items': []},
                    'CustomOriginConfig': {
                        'HTTPPort': 80,
                        'HTTPSPort': 443,
                        'OriginProtocolPolicy': 'http-only',
                        'OriginSslProtocols': {'Quantity': 1, 'Items': ['TLSv1']},
                        'OriginReadTimeout': 30,
                        'OriginKeepaliveTimeout': 5
                    }
                },
            ]
        },
        'Enabled': True,
        'Comment': '',
        'PriceClass': 'PriceClass_100',
        'Logging': {
            'Enabled': False,
            'IncludeCookies': False,
            'Bucket': '',
            'Prefix': ''
        },
        'CacheBehaviors': {'Quantity': 0},
        'Restrictions': {
            "GeoRestriction": {
                "RestrictionType": 'none',
                "Quantity": 0
            }
        },
        "DefaultRootObject": "index.html",
        "WebACLId": "",
        "HttpVersion": "http2",
        'DefaultCacheBehavior': {
            'TargetOriginId': id,
            'ForwardedValues': {
                'QueryString': False,
                'Cookies': {'Forward': 'none'},
                'Headers': {'Quantity': 0, 'Items': []},
                'QueryStringCacheKeys': {'Quantity': 0, 'Items': []}
            },
            'TrustedSigners': {'Enabled': False, 'Quantity': 0, 'Items': []},
            'ViewerProtocolPolicy': 'redirect-to-https',
            'MinTTL': 0,
            'AllowedMethods': {
                'Quantity': 2,
                'Items': ['GET', 'HEAD'],
                'CachedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']}
            },
            'DefaultTTL': 86400,
            'MaxTTL': 31536000,
            'Compress': True,
            'LambdaFunctionAssociations': {'Quantity': 0},
            'FieldLevelEncryptionId': ''
        },
        'CustomErrorResponses': {'Quantity': 0},
        'ViewerCertificate': {
            'ACMCertificateArn': ssl_arn,
            'SSLSupportMethod': 'sni-only',
            'MinimumProtocolVersion': 'TLSv1.1_2016',
            'CertificateSource': 'acm'
        },
        'Restrictions': {
            'GeoRestriction': {'RestrictionType': 'none', 'Quantity': 0}
        },
        'WebACLId': '',
        'HttpVersion': 'http2'
    }
