import os
from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

install_requires = [
    "boto3",
    "pyyaml",
    "click",
    "halo",
    "tldextract"
]

setup(
    name="s3lify",
    version="0.1.0",
    license="MIT",
    author="Mardix",
    author_email="macx2082@gmail.com",
    description="A script to deploy secure (SSL) single page application (SPA) or HTML static site on AWS S3, using S3, Route53, Cloudfront and ACM.",
    url="https://github.com/mardix/s3lify",
    long_description=long_description,
    long_description_content_type="text/markdown",
    py_modules=['s3lify'],
    entry_points=dict(console_scripts=[
        's3lify=s3lify.cli:main',
        's3l=s3lify.cli:main',
    ]),
    include_package_data=True,
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    install_requires=install_requires,
    keywords=[],
    platforms='any',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    zip_safe=False
)

