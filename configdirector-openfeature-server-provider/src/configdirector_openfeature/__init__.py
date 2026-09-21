"""OpenFeature server provider for ConfigDirector.

ConfigDirector is a remote configuration and feature flag service.

Example::

    from configdirector_openfeature import ConfigDirectorProvider
    from openfeature import api

    api.set_provider_and_wait(ConfigDirectorProvider("YOUR-SERVER-SDK-KEY"))

    if api.get_client().get_boolean_value("new-checkout", False):
        ...
"""

from ._version import __version__
from .provider import ConfigDirectorProvider

__all__ = ["ConfigDirectorProvider", "__version__"]
