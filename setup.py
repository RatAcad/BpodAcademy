import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="bpod-academy",
    version="0.0b0",
    author="Gary Kane",
    author_email="gakane@bu.edu",
    description="A simple GUI to control multiple Bpod devices",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/gkane26/BpodAcademy",
    packages=setuptools.find_packages(),
    install_requires=[
        "pyserial",
        "scipy",
        "multiprocess",
        "kthread",
        "pyzmq",
        "pillow",
        "opencv-python",
        "scikit-video",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPL-3)",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "console_scripts": [
            "bpodacademy=bpodacademy.bpodacademy:main",
            "bpodacademy-server=bpodacademy.server:main",
        ]
    },
    python_requires=">=3.6",
)
