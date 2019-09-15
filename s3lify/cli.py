
import os
import re
import sys
import yaml
import time
import json
import click
import pkg_resources
from . import S3lify
from halo import Halo

NAME = "S3lify"
CWD = os.getcwd()
CONFIG_FILE = "%s/%s" % (CWD, "s3lify.yml")
sp = Halo()


def header(title=None, domain_name=None):
    print("")
    print("-" * 80)
    print(":: %s ::" % NAME)
    if domain_name:
        print("Domain: %s" % domain_name)
    print("-" * 80)  
    if title:  
        print("* %s *" % title.upper())
        print('')

def footer():
    print("")
    print("-" * 80) 
    print("")

def site_404_message(domain):
    print("")
    sp.fail("ERROR")
    print("Domain: %s " % domain)
    print("Site doesn't exist, or hasn't been setup yet!")
    print("Verify the s3lify.yml config file")
    print("or run 's3lify setup' to setup the site")

def create_config_file():
    if not os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "wb") as f:
            f.write(pkg_resources.resource_string(__name__, "s3lify.yml"))


def main():

    # init
    if len(sys.argv) == 2 and sys.argv[1] == "init":
        header()
        if os.path.isfile(CONFIG_FILE):
            print("'s3lify.yml' exists already in %s" % CWD)
        else:
            create_config_file()
            print("'s3lify.yml'created in %s" % CWD)
            print("edit the 's3lify.yml' config, then run 's3lify setup'")
        footer()
        return


    # Missing config
    if not os.path.isfile(CONFIG_FILE):
        header()
        sp.fail("ERROR")
        print("missing 's3lify.yml' in %s " % CWD)
        print("run 's3lify init' to create 's3lify.yml' in %s" % CWD)
        footer()
        return

    # Good to go

    # Load config
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)

    domain_name = config.get("domain")
    client = S3lify(domain=domain_name,
                    aws_access_key_id=config.get("aws_access_key_id"),
                    aws_secret_access_key=config.get("aws_secret_access_key"),
                    region=config.get("aws_region"),
                    )

    distribution = config.get('distribution', 's3') or ''
    if distribution not in ['s3', 'route53', 'cloudfront']:
        distribution = 's3'
    distribution = distribution.lower()

    @click.group()
    def cli():
        """ S3lify, a simple python tool to deploy SPA or static site to S3 using S3, Route53, Cloudfront and ACM """

    @cli.command()
    def setup():
        """
        To setup a brand new site
        """

        header(title="Setup", domain_name=domain_name)

        update_route53domains_dns = config.get('update_route53domains_dns')
        if update_route53domains_dns is None:
            update_route53domains_dns = True

        print("")
        sp.info('Distribution: %s' % distribution)

        if not client.site_exists:
            client.s3_create_site()
        sp.succeed("Site created on S3: OK")

        # Distribution: s3|route53|cloudfront
        #
        if distribution in ["route53", "cloudfront"]:
            # setup route53
            client.s3_update_route53_a_records()
            sp.succeed('DNS updated on Route53: OK')

            # update domains DNS
            if update_route53domains_dns is True:
                if client.route53domains_update_dns():
                    sp.succeed('Domain Name Servers updated: OK')

            # cloudfront specific
            if distribution == 'cloudfront':

                # SSL: Certificate
                cert_status = client.acm_get_certificate_status()
                if not cert_status:
                    sp.info('Creating new ACM SSL certificate')
                    client.acm_generate_certificate()
                    time.sleep(2)
                    cert_status = client.acm_get_certificate_status()
                    time.sleep(2)
                    sp.succeed('Created SSL certificate: OK')
                sp.succeed('Certificate status: %s ' % cert_status)

                # Update the CNAME with ACM route53 data
                if cert_status != "ISSUED":
                    time.sleep(2)
                    if client.acm_update_route53_cname_records():
                        sp.succeed('Set SSL certificate Route53 CNAME: OK')

                # Cloudfront
                dist_id = client.cloudfront_get_distribution_id()
                if not dist_id:
                    sp.info('Creating cloudfront distribution id')
                    time.sleep(2)
                    client.cloudfront_create_distribution()
                    dist_id = client.cloudfront_get_distribution_id()
                    sp.succeed('Distribution created: OK')
                sp.succeed('Distribution ID: %s' % dist_id)
                sp.succeed('Distribution Domain Name: %s' % client.cloudfront_get_distribution_domain_name())

                # Add cloudfront domain name to A records
                client.cloudfront_update_route53_a_records()

                time.sleep(2)

                # DONE...
        # S3
        else:
            sp.info('Site will be available from AWS S3 only')

        sp.clear()
        sp.succeed('Done!')
        print("")
        print("URL: %s " % client.domain_url)
        print("S3 : %s " % client.s3_url)
        footer()

    @cli.command()
    def deploy():
        """
        Deploy the site
        """

        header(title="Deploy site", domain_name=domain_name)

        if not client.site_exists:
            site_404_message(domain_name)
            footer()
            return

        site_directory = os.path.join(CWD, config.get('site_directory'))
        client.s3_create_manifest()
        sp.succeed('Manifest file created: OK')

        if not config.get('purge_files'):
            sp.warn('config.purge_files is disabled')
        else:
            exclude_files = config.get("purge_exclude_files", [])
            client.s3_purge_files(exclude_files=exclude_files)
            sp.succeed('Files purged from S3: OK')

        if not config.get('invalidate_cloudfront_objects'):
            sp.warn('invalidate_cloudfront_objects is False')
        else:
            client.cloudfront_invalidate_objects()
            sp.succeed('Invalidated cloudfront objects: OK')

        sp.info('uploading site directory to S3...')
        client.s3_upload(site_directory)
        sp.succeed('Site files uploaded: OK')
        sp.succeed('Site deployed successfully: OK')
        sp.clear()
        sp.succeed('Done!')
        print("")
        print("URL: %s " % client.domain_url)
        print("S3 : %s " % client.s3_url)
        footer()

    @cli.command()
    def status():
        """
        Show status and info of the site
        """

        header(title="Site Status", domain_name=domain_name)

        if not client.site_exists:
            site_404_message(config.get("domain"))
            footer()
            return

        print("---")
        print("URL : %s " % client.domain_url)
        
        print("---")
        print("S3")
        print("Site created: %s " % ('OK' if client.site_exists else 'Failed'))
        print("URL : %s " % client.s3_url)

        if distribution != "s3":
            print("---")
            print("ACM")
            print("Certificate status: %s " % client.acm_get_certificate_status())

            print("---")
            print("Cloudfront")
            print("Distribution id: %s " % client.cloudfront_get_distribution_id())
            print("Domain name: %s " % client.cloudfront_get_distribution_domain_name())

            ns_values = client.route53_get_ns_values()
            if ns_values:
                print("---")
                print("Name Servers")
                print(("\n".join(ns_values)))
        else:
            print("Deployment: site is available from AWS S3 only")
        footer()

    # Init cli
    print('Domain: %s' % client.domain)
    cli()
