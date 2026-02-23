from setuptools import setup, find_packages

setup(
    name="streammachine",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "coredis>=4.22.0",
        "venusian",
        "uvloop",
    ],
    python_requires=">=3.8",
)
