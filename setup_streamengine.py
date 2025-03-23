from setuptools import setup, find_packages

setup(
    name="streamengine",
    setup_requires=['streamengine'],
    use_scm_version=True,
    packages=find_packages(),
    include_package_data=True,
)

