magic-module-skaffolder
=======================

generates or updates a Magic Module Resource definitions with the metadata
of the Google Cloud APIs.

When generating the definitions, it will first use the `ga` interface, and
supplement the definition with the `beta` interface, so that it can
determine which fields are only available on the `beta` interface.

The resulting definitions are not perfect and may need some polishing. Most
properties required by the magic module are derived from the free text
description field. So, please do check the result.

Existing field definitions are not overwritten, so once inspected and
correct you can rerun the merge operation as often as you want. Note that
fields of a resource which do not exist in the API are removed.

example - update
==============
To update an existing resource definition, type:

```
$ mm-skaffolder update --inplace --resource-file tests/mmv1/products/compute/BackendService.yaml

INFO: adding port as ga field to definition of BackendService
INFO: adding kind as ga field to definition of BackendService
INFO: adding network as ga field to definition of BackendService
INFO: adding maxStreamDuration as ga field to definition of BackendService
INFO: adding region as ga field to definition of BackendService
INFO: adding connectionTrackingPolicy as ga field to definition of BackendService
INFO: adding failoverPolicy as ga field to definition of BackendService
INFO: adding subsetting as ga field to definition of BackendService
INFO: adding selfLink as ga field to definition of BackendService
INFO: adding serviceBindings as ga field to definition of BackendService
INFO: adding failover as ga field to definition of BackendService.backends.
INFO: keeping beta field connectTimeout from definition of BackendService.circuitBreakers in ga 
INFO: adding requestCoalescing as ga field to definition of BackendService.cdnPolicy
INFO: adding signedUrlKeyNames as ga field to definition of BackendService.cdnPolicy
INFO: adding bypassCacheOnRequestHeaders as ga field to definition of BackendService.cdnPolicy
WARNING: mismatch in field name BackendService.localityLbPolicies: expected "localityLbPolicyConfig" defined ""
INFO: adding optionalFields as ga field to definition of BackendService.logConfig
INFO: adding optionalMode as ga field to definition of BackendService.logConfig
WARNING: mismatch in field name BackendService.localityLbPolicies: expected "localityLbPolicyConfig" defined ""
INFO: adding authentication as beta field to definition of BackendService.securitySettings
INFO: adding awsV4Authentication as beta field to definition of BackendService.securitySettings
INFO: adding subsetSize as beta field to definition of BackendService.subsetting
```

example - generate
==============
To generate a new resource definition, type:

```shell
$ mm-skaffolder generate \
   --product-directory tests/mmv1/products/networksecurity \
   serverTlsPolicies addressGroups
INFO: Writing to definition of ServerTlsPolicy to tests/mmv1/products/networksecurity/ServerTlsPolicy.yaml

```
