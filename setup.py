#!/usr/bin/env python3
"""Opsora CLI — Multi-provider AI coding assistant for the terminal."""

from pathlib import Path
from setuptools import setup, find_packages

here = Path(__file__).parent.resolve()

# Read long description from README
long_description = ""
readme_path = here / "README.md"
if readme_path.is_file():
    long_description = readme_path.read_text(encoding="utf-8")

setup(
    name="opsora-cli",
    version="2.1.0",
    description="Multi-provider AI coding assistant with a Codex/Cursor-style terminal UI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/opsora/opsora-cli",
    author="Opsora",
    author_email="hello@opsora.dev",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development",
        "Topic :: Utilities",
    ],
    keywords="ai, coding-assistant, cli, terminal, multi-provider, llm, copilot",
    python_requires=">=3.10",
    packages=find_packages(),
    py_modules=["opsora_v2"],
    package_dir={"": "cmd"},
    install_requires=[
        "openai>=1.0.0",
        "rich>=13.0.0",
        "prompt-toolkit>=3.0.0",
        "boto3>=1.28.0",
        "requests>=2.28.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "ruff>=0.1.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "opsora=opsora_v2:main",
            "opsora2=opsora_v2:main",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/opsora/opsora-cli/issues",
        "Source": "https://github.com/opsora/opsora-cli",
        "Documentation": "https://github.com/opsora/opsora-cli#readme",
    },
)
