import setuptools

with open('README.md') as f:
    long_desc = f.read()

setuptools.setup(
        name="vuespa",
        version="0.3.3",
        author="Walt Woods",
        author_email="woodswalben@gmail.com",
        description="Helper library for Python+Vue Single Page Applications",
        long_description=long_desc,
        long_description_content_type='text/markdown',
        url='https://github.com/wwoods/python-vuespa',
        packages=setuptools.find_packages(),
        install_requires=[
            'aiohttp',
        ],
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
        ],
)

