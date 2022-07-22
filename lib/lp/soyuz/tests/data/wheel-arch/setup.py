from setuptools import Extension, setup

setup(
    name="wheel-arch",
    version="0.0.1",
    description="Example description",
    long_description="Example long description",
    url="http://example.com/",
    ext_modules=[Extension("_test", sources=["test.c"])],
)
