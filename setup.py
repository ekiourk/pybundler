import os

from setuptools import setup, find_packages

setup(
    name='pybundler',
    version='0.1.5',
    packages=find_packages(exclude=['tests*']),
    install_requires=[],  # Add any dependencies your project might have here
    author='Your Name',
    author_email='your.email@example.com',
    description='A python project bundler',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    url='https://github.com/ekiourk/pybundler',
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
    entry_points={
        'console_scripts': [
            'pybundle=pybundler.main:main',
        ],
    },
)
