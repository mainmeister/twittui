import os
from setuptools import setup, find_packages

setup(
    name="twittui",
    version="1.0.2",
    description="TWiT.tv Terminal & Desktop Media Browser",
    long_description=open("README.md", encoding="utf-8").read() if os.path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="TWiT Community",
    py_modules=["main", "installer", "twittui_form", "toga_textual_backend", "generate_icon"],
    entry_points={
        "console_scripts": [
            "twittui=main:main",
        ],
    },
    install_requires=[
        "toga>=0.4.0",
        "toga-gtk>=0.4.0",
        "toga-textual>=0.4.0",
        "textual>=0.40.0",
        "requests>=2.28.0",
        "python-dotenv>=1.0.0",
    ],
    package_data={
        "": [
            "feed-style.css",
            "feed-style.xsl",
            "twittv.apib",
            "README.md",
            "resources/*",
        ],
    },
    include_package_data=True,
    python_requires=">=3.10",
)
