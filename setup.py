#!/usr/bin/env python
from setuptools import find_packages, setup

with open("README.rst") as file_:
    long_description = file_.read()

setup(
    name="django-syzygy",
    version="1.2.1",
    description="Deployment aware tooling for Django migrations.",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    url="https://github.com/charettes/django-syzygy",
    author="Simon Charette",
    author_email="charette.s@gmail.com",
    install_requires=["Django>=4.2"],
    packages=find_packages(exclude=["tests", "tests.*"]),
    license="MIT License",
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Django",
        "Framework :: Django :: 4.2",
        "Framework :: Django :: 5.0",
        "Framework :: Django :: 5.1",
        "Framework :: Django :: 5.2",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
