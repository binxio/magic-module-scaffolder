magic-module-scaffolder
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

Warning
=======
Do not use the scaffolder to generate PR on the magic-modules without careful
inspection of the generated changes. The changes are generated based on what
we can derive from the field description in the discovery document, and it
may not always be correct.

Use it as a way to bootstrap updates and determine whether new features
have been added with respect to the existing resource definition.


example - update
==============
To update an existing resource definition, type:

```
$ mm-scaffolder update --inplace --resource-file mmv1/products/compute/BackendService.yaml

 mm-scaffolder update --inplace --resource-file mmv1/products/compute/BackendService.yaml
INFO: adding serviceBindings as ga field to definition of BackendService
INFO: adding kind as ga field to definition of BackendService
INFO: adding selfLink as ga field to definition of BackendService
INFO: adding usedBy as ga field to definition of BackendService
INFO: adding metadatas as ga field to definition of BackendService
INFO: adding network as ga field to definition of BackendService
INFO: adding port as ga field to definition of BackendService
INFO: adding region as ga field to definition of BackendService
INFO: adding connectionTrackingPolicy as ga field to definition of BackendService
INFO: adding subsetting as ga field to definition of BackendService
INFO: adding failoverPolicy as ga field to definition of BackendService
INFO: adding maxStreamDuration as ga field to definition of BackendService
INFO: adding failover as ga field to definition of BackendService.backends.
INFO: adding requestCoalescing as ga field to definition of BackendService.cdnPolicy
INFO: adding signedUrlKeyNames as ga field to definition of BackendService.cdnPolicy
INFO: adding enabled as ga field to definition of BackendService.iap
WARNING: mismatch in field name BackendService.localityLbPolicies: expected "localityLbPolicyConfig" defined ""
INFO: adding awsV4Authentication as ga field to definition of BackendService.securitySettings
INFO: adding optionalMode as ga field to definition of BackendService.logConfig
INFO: adding optionalFields as ga field to definition of BackendService.logConfig
INFO: adding ipAddressSelectionPolicy as beta field to definition of BackendService
INFO: adding serviceLbPolicy as beta field to definition of BackendService
INFO: adding preference as beta field to definition of BackendService.backends.
WARNING: mismatch in field name BackendService.localityLbPolicies: expected "localityLbPolicyConfig" defined ""
INFO: adding authentication as beta field to definition of BackendService.securitySettings
INFO: adding subsetSize as beta field to definition of BackendService.subsetting
```

example - generate
==============
To generate a new resource definition, type:

```shell
$ mm-scaffolder generate \
   --product-directory tests/mmv1/products/networksecurity \
   serverTlsPolicies
INFO: Writing to definition of ServerTlsPolicy to tests/mmv1/products/networksecurity/ServerTlsPolicy.yaml
```

install
======
to install, type:

```
pip install magic-module-scaffolder
```
