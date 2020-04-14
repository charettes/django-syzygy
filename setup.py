#!/usr/bin/env python
from __future__ import unicode_literals

from setuptools import find_packages, setup

with open("README.rst") as file_:
    long_description = file_.read()

setup(
    name="django-syzygy",
    version="0.0.1",
    description="",
    long_description=long_description,
    url="https://github.com/charettes/django-syzygy",
    author="Simon Charette",
    author_email="charette.s@gmail.com",
    install_requires=["Django>=2.2"],
    packages=find_packages(exclude=["tests", "tests.*"]),
    license="MIT License",
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Django",
        "Framework :: Django :: 2.2",
        "Framework :: Django :: 3.0",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
