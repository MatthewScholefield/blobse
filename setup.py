from setuptools import setup

setup(
    name='blobse',
    version='0.1.0',
    description='Simple small blob store over HTTP',
    url='https://github.com/MatthewScholefield/blobse',
    author='Matthew D. Scholefield',
    author_email='matthew331199@gmail.com',
    classifiers=[
        'Development Status :: 3 - Alpha',

        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    keywords='blobse',
    packages=['blobse'],
    install_requires=[
        'uvicorn',
        'fastapi',
        'loguru',
        'pydantic[dotenv]',
        'loguru-logging-intercept',
        'uvicorn-loguru-integration',

        'fastapi_plugins',
        'aioredis'
    ],
    entry_points={
        'console_scripts': [
            'blobse=blobse.__main__:main'
        ],
    }
)
