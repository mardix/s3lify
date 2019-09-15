
# S3lify

---

**S3lify**, a script to deploy secure (SSL) single page application (SPA) or HTML static site on AWS S3, using S3, Route53, Cloudfront and ACM.

---

## How does it work?

### Install

Install S3lify. It's a Python script, run the pip command below

`pip install s3lify`

Then navigate to the root of the directory that contains your site, then initialize S3lify

`s3lify init`

Then edit the config file `s3lify.yml` to match your site's information



### Setup Process

Setup S3lify 

`s3lify setup`

- It creates the website on S3 by creating a new website bucket
- It creates an DNS entry on Route53 pointing to S3 website bucket
- It provisions an SSL certificate using ACM, and validates the domain by adding the and ACM CNAME on Route53
- *(If the domain is purchased through Route53Domains, it will update the DNS server name)*
- It creates a new Cloudfront distribution and attaches the SSL certificate provided by ACM
- It updates the Route53 with the Cloudfront's domain name
- Now your SSL site is ready to deploy. You will be able to access your site via 'https://yoursite.com'
- Ready to deploy!

### Deploy Process

`s3lify deploy`

- It purges all files in S3 bucket
- It invalidates all objects in cloudfront
- Upload the directory to S3
- Sites updated successfully
- That's it!

---

#### AWS Service Used

- S3
- Route53
- Route53 Domains
- Cloudfront
- ACM

---

## FAQ

- Can I use only S3 website?

Yes. In the *s3lify.yml* set `distribution: s3`

- I deploy my site, but I don't see the changes.

Make sure you build your site first, then run `s3lify deploy`


---

## Commands

`pip install s3lify`: Install S3lify

`s3lify init`: Init S3lify in the directory

`s3lify setup`: Setup S3lify and all the AWS services needed

`s3lify deploy`: Deploy the site

`s3lify status`: see the status of the site



---

## Config

At the root of the directory, outside of the build folder, create the config file `s3lify.yml`

```yml

# s3lify.yml
# -----------------------------------------------------------------------------
# S3lify config
# -----------------------------------------------------------------------------

#:: AWS credentials and region
aws_region: us-east-1
# aws_access_key_id: 
# aws_secret_access_key: 

#:: Site Info
# The domain without the 'www.'. It will create the S3 bucket with it
domain:  # 'mysite.com'

# The directory containing the site to upload, from the CWD running s3now
site_directory: ./mysite

# For working with SPA, point the error_file to 'index.html' 
index_file: index.html # index.html
error_file: error.html # error.html

#:: Purge files.
purge_files: True         # To delete all the files on S3
purge_exclude_files:      # Files not to delete on purge
  - index.html
  - error.html

#:: distribution
# The type of distribution
# s3 | route53 | cloudfront
# default: s3
# s3: to deploy to s3 only
# route53: will deploy on s3 and set the domain on Route53
# cloudfront: deploy on s3, set route53, set ACM for SSL and activate cloudfront 
distribution: cloudfront

#:: update_route53domains_dns
# default: True
# when true it will attempt to update the domain DNS with the route53 Name servers
update_route53domains_dns: True

#:: invalidate_cloudfront_objects
# To invalidate cloudfront objects, so it can retrieve new contents
invalidate_cloudfront_objects: True

```

---

License: MIT
