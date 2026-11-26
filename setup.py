import os
from setuptools import setup


def _read_readme() -> str:
    readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
    if not os.path.exists(readme_path):
        return ""
    with open(readme_path, "r", encoding="utf-8") as fh:
        return fh.read()


setup(
    name="twittui",
    version="1.1.0",
    description="TWiT.tv Terminal & Desktop Media Browser",
    long_description=_read_readme(),
    long_description_content_type="text/markdown",
    author="TWiT Community",
    packages=["twittui", "twittui.search", "twittui.ui"],
    py_modules=[
        "main",
        "installer",
        "twittui_form",
        "toga_textual_backend",
        "generate_icon",
        "tiered_search",
        "double_metaphone",
    ],
    entry_points={
        "console_scripts": [
            "twittui=main:main",
        ],
    },
    install_requires=[
        "toga>=0.4.0",
        "toga-gtk>=0.4.0; sys_platform == 'linux'",
        "toga-textual>=0.4.0",
        "textual>=0.40.0",
        "requests>=2.28.0",
        "python-dotenv>=1.0.0",
        "yt-dlp>=2023.1.1",
    ],
    extras_require={
        "gtk": [
            "toga-gtk>=0.4.0",
            "PyGObject>=3.42.0",
            "pycairo>=1.20.0",
        ],
        "textual": [
            "toga-textual>=0.4.0",
            "textual>=0.40.0",
        ],
        "youtube": [
            "yt-dlp>=2023.1.1",
        ],
        "security": [
            "defusedxml>=0.7.1",
            "nh3>=0.2.14",
        ],
        "fast-search": [
            "rapidfuzz>=3.0.0",
        ],
        "xml": [
            "lxml>=4.9.0",
        ],
        "dev": [
            "PyYAML>=6.0",
            "ruff>=0.4.0",
            "mypy>=1.8.0",
        ],
    },
    package_data={
        "twittui": ["resources/*"],
    },
    include_package_data=True,
    python_requires=">=3.10",
)
