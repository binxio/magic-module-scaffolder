import logging
from pathlib import Path
from typing import Optional, Dict, Any

import click
from pattern.text.en import singularize
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from magic_module_skaffolder.api_descriptions import (
    APIMetaData,
    SchemaTypeDefinition,
)
from magic_module_skaffolder.magic_module import Product, Field, Resource

yaml = YAML(typ="rt")
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.preserve_quotes = True
yaml.width = 255


class Skaffolder:
    """
    generates or updates a Magic Module Resource definition with the metadata of the
    Google Cloud APIs.
    """

    def __init__(self):
        pass

    def create_magic_module_field(
        self,
        api: APIMetaData,
        name: Optional[str],
        type_definition: SchemaTypeDefinition,
    ) -> Field:
        """
        creates a Magic Module field definition from a JSON schema type definition,
        :param api: the metadata of the api
        :param name:  the name of the field if any
        :param type_definition: the json schema definition of the field
        :return: a Magic Module field definition
        """
        result: Dict[str, Any] = {"name": name} if name else {}
        description = type_definition.description
        if description:
            result["description"] = (
                LiteralScalarString(description)
                if description.count("\n") > 1
                else description
            )

        if type_definition.is_output_only:
            result["output"] = True

        if type_definition.is_input_only:
            result["ignore_read"] = True

        if type_definition.is_required:
            result["required"] = True

        value_type = type_definition.value_type
        value_format = type_definition.value_format
        target_type = {
            "double": "Api::Type::Double",
            "float": "Api::Type::Double",
            "int32": "Api::Type::Integer",
            "int64": "Api::Type::Integer",
            "uint32": "Api::Type::Integer",
            "uint64": "Api::Type::Integer",
        }.get(value_format) if value_type == 'string' else None

        if not value_type:
            ref = type_definition.get("$ref")
            if not ref:
                raise ValueError(f"no type nor $ref found in {name}")

            referenced_type = api.get_schema_type_definition(ref)
            result = self.create_magic_module_field(api, name, referenced_type)

        elif value_type == "integer":
            result["type"] = "Api::Type::Integer"
        elif value_type == "number":
            result["type"] = "Api::Type::Double"
        elif value_type == "string":
            if "enum" in type_definition:
                result["type"] = "Api::Type::Enum"
                result["values"] = [f":{value}" for value in type_definition["enum"]]
            elif target_type:
                result["type"] = target_type
            elif value_format == "byte" and name == "fingerprint":
                result["type"] = "Api::Type::Fingerprint"
            elif "in RFC3339 text format" in description or (
                name and "timestamp" in name.lower()
            ):
                result["type"] = "Api::Type::Time"
            elif type_definition.is_resource_ref:
                # see https://googlecloudplatform.github.io/magic-modules/docs/how-to/add-mmv1-resource/#resourceref
                resource_reference = type_definition.is_resource_ref.group(1)
                (
                    resource_reference_name,
                    resource_reference_type,
                ) = resource_reference.split(".", 1)
                result["resource"] = resource_reference_type
                result["imports"] = (
                    "selfLink" if resource_reference_name == "compute" else "name"
                )
                result["type"] = "Api::Type::ResourceRef"
            else:
                result["type"] = "Api::Type::String"
        elif value_type == "boolean":
            result["type"] = "Api::Type::Boolean"
        elif value_type == "array":
            result["type"] = "Api::Type::Array"
            result["item_type"] = self.create_magic_module_field(
                api, None, SchemaTypeDefinition(type_definition["items"])
            )
        elif value_type == "object":
            if "properties" not in type_definition:
                if (
                    type_definition.get("additionalProperties", {}).get("type")
                    == "string"
                ):
                    result["type"] = "Api::Type::KeyValuePairs"
                else:
                    raise ValueError("object type is missing properties")
            else:
                result["type"] = "Api::Type::NestedObject"
                properties = []
                for (
                    property_name,
                    property_definition,
                ) in type_definition.properties.items():
                    properties.append(
                        self.create_magic_module_field(
                            api, property_name, property_definition
                        )
                    )
                result["properties"] = properties
        else:
            raise ValueError(f"unexpected type {value_type}")

        return Field.create(result)

    def create_magic_module_resource(
        self, api: APIMetaData, resource_name: str, type_name: str
    ) -> Resource:
        """
        Creates a magic module resource definition for the type `type_name` of the `resource_name`
        in the `api`.
        """
        resource_definition = api.get_resource_definition(resource_name)

        method = resource_definition.get_insert_or_create_method()
        type_definition = api.get_schema_type_definition(type_name)
        result = Resource({"name": type_name, "base_url": method.flat_path})
        if type_definition.kind:
            result["kind"] = type_definition.kind

        result.update(self.create_magic_module_field(api, None, type_definition))
        return result


@click.group()
def main():
    """
    generates or updates a Magic Module Resource definitions with the metadata of the
    Google Cloud APIs.

    When generating the definitions, it will first use the `ga` interface, and supplement the
    definition with the `beta` interface, so that it can determine which fields are only
    available on the `beta` interface.

    The resulting definitions are not perfect and may need some polishing. Most properties required
    by the magic module are derived from the free text description field. So, please do check
    the result.

    Existing field definitions are not overwritten, so once inspected and correct you can
    rerun the merge operation as often as you want. Note that fields of a resource which do not
    exist in the API are removed.
    """
    pass


@main.command()
@click.option(
    "--product-directory",
    required=True,
    type=click.Path(file_okay=False, exists=True),
    help="the Magic Module product directory the resource definitions belong to",
)
@click.argument("resource", nargs=-1, required=True)
def generate(
    product_directory: str,
    resource: tuple[str],
):
    """
    generates a resource definition for the specified resources. It will derive the type from
    the resource name. So the resource name `backendServices` will have type `BackendService`
    as its resource type definition.
    """
    product_definition_file = Path(product_directory).joinpath(
        "product.yaml"
    )
    if not product_definition_file.exists():
        click.echo(
            f"'{product_directory} is not a magic module product directory",
            err=True,
        )

    product_definition = Product.load(product_definition_file)
    updater = Skaffolder()
    for resource_name in resource:
        type_name = (
            singularize(resource_name)[0].upper() + singularize(resource_name)[1:]
        )
        existing = None
        for provider_version, api_id in product_definition.get_api_ids():
            api = APIMetaData.load(api_id)
            defined = updater.create_magic_module_resource(
                api, resource_name, type_name
            )
            if existing:
                Resource.merge_resources(existing, defined, provider_version)
            else:
                existing = defined

        output_file = Path(product_directory).joinpath(f"{type_name}.yaml")
        logging.info("Writing to definition of %s to %s", type_name, output_file)
        with open(output_file, "w") as file:
            yaml.dump(existing, file)


@main.command()
@click.option(
    "--resource-file",
    type=click.Path(dir_okay=False, exists=True),
    required=True,
    help="containing the magic module resource definition",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False),
    required=False,
    help="to write updated magic module resource file to",
)
def update(resource_file: str, output_file: str):
    """
    updates the resource definition in the resource-file to match the latest API specification.
    If the output-file is not specified, then the result will be written back into the resource-file.
    """
    if not output_file:
        output_file = resource_file

    product_definition_file = Path(resource_file).parent.joinpath(
        "product.yaml"
    )
    if not product_definition_file.exists():
        click.echo(
            f"magic module product definition file '{product_definition_file} not found",
            err=True,
        )

    product_definition = Product.load(product_definition_file)

    existing: Optional[Resource] = None
    try:
        existing = Resource.load(resource_file)
    except ValueError as error:
        click.echo(str(error), err=True)

    type_name = existing["name"]
    api_name, _ = existing["kind"].split("#")
    resource_name = existing["base_url"].split("/")[-1]

    updater = Skaffolder()

    for provider_version, api_id in product_definition.get_api_ids():
        api = APIMetaData.load(api_id)
        defined = updater.create_magic_module_resource(api, resource_name, type_name)
        Resource.merge_resources(existing, defined, provider_version)

    with open(output_file, "w") as file:
        yaml.dump(existing, file)