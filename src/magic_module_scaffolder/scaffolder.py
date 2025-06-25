import logging
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Optional, Dict, Any

import click
from textblob import Word
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from magic_module_scaffolder.api_descriptions import (
    APIMetaData,
    SchemaTypeDefinition,
)
from magic_module_scaffolder.magic_module import Product, Field, Resource

yaml = YAML(typ="rt")
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.preserve_quotes = True
yaml.preserve_whitespace = True
yaml.width = 255

def singularize(word: str) -> str:
    return Word(word).singularize()

class Scaffolder:
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
                if description.count("\n") >= 1
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
        target_type = (
            {
                "double": "Api::Type::Double",
                "float": "Api::Type::Double",
                "int32": "Api::Type::Integer",
                "int64": "Api::Type::Integer",
                "uint32": "Api::Type::Integer",
                "uint64": "Api::Type::Integer",
                "google-datetime": "Api::Type::Time",
            }.get(value_format)
            if value_type == "string"
            else None
        )

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
            elif name == "etag":
                result["type"] = "Api::Type::Fingerprint"
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
                    if name == "labels":
                        result["type"] = "Api::Type::KeyValueLabels"
                    elif name == "annotations":
                        result["type"] = "Api::Type::KeyValueAnnotations"
                    else:
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
                if len(properties) == 1:
                    properties[0]["required"] = True
                result["properties"] = properties
        else:
            raise ValueError(f"unexpected type {value_type}")

        return Field.create(result)

    def generate_magic_module_resource_properties(
        self, api, resource_name, type_name, schema_type_name
    ) -> (dict, bool):
        """
        generates the properties for the magic module resource definition. Unfamiliarity with
        the magic modules and their mapping from api definition, makes this a best effort
        approach.
        """
        result = {"name": type_name}
        type_definition = api.get_schema_type_definition(schema_type_name)
        if type_definition.kind:
            result["kind"] = type_definition.kind

        resource_definition = api.get_resource_definition(resource_name)
        method = resource_definition.get_insert_or_create_method()

        def parameter_camel_case_to_snake_case(name: str):
            name = name.removesuffix("Id")
            name = singularize(name)
            name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
            return name

        def add_base_url():
            """
            the base url is without the version prefix and appears
            to have all variable references in the definition replaced
            with a snake case, singular variable. eg. {projectsId} -> {{project}}.
            :return:
            """
            base_url = (
                method.flat_path[len(api.api_version) + 1 :]
                if method.flat_path.startswith(api.api_version + "/")
                else method.flat_path
            )

            def _singular_snake_case(match: re.Match) -> str:
                return "{{" + parameter_camel_case_to_snake_case(match.group(1)) + "}}"

            base_url = re.sub(r"{([^}]*)}", _singular_snake_case, base_url)
            result["base_url"] = base_url

        def add_self_link():
            if "self_link" in type_definition.properties.keys():
                result["has_self_link"] = True
            elif "name" in type_definition.properties.keys():
                result["self_link"] = result["base_url"] + "/{{name}}"

        def add_update_verb():
            patch_method = resource_definition.methods.get("patch")
            if patch_method:
                result["update_verb"] = ":PATCH"
                if "updateMask" in patch_method.parameters:
                    result["update_mask"] = True

        def add_async_operation():

            new_style_async = yaml.load(
                textwrap.dedent(
                    """
                autogen_async: true
                async: !ruby/object:Api::OpAsync
                  operation: !ruby/object:Api::OpAsync::Operation
                    path: 'name'
                    base_url: '{{op_id}}'
                    wait_ms: 1000
                    timeouts: !ruby/object:Api::Timeouts
                      insert_minutes: 30
                      update_minutes: 30
                      delete_minutes: 30
                  result: !ruby/object:Api::OpAsync::Result
                    path: 'response'
                  status: !ruby/object:Api::OpAsync::Status
                    path: 'done'
                    complete: true
                    allowed:
                      - true
                      - false
                  error: !ruby/object:Api::OpAsync::Error
                    path: 'error'
                    message: 'message'
            """
                )
            )

            old_style_async = yaml.load(
                textwrap.dedent(
                    """
                autogen_async: true
                async: !ruby/object:Api::OpAsync
                  operation: !ruby/object:Api::OpAsync::Operation
                    kind: 'compute#operation'
                    path: 'name'
                    base_url: 'projects/{{project}}/global/operations/{{op_id}}'
                    wait_ms: 1000
                  result: !ruby/object:Api::OpAsync::Result
                    path: 'targetLink'
                  status: !ruby/object:Api::OpAsync::Status
                    path: 'status'
                    complete: 'DONE'
                    allowed:
                      - 'PENDING'
                      - 'RUNNING'
                      - 'DONE'
                  error: !ruby/object:Api::OpAsync::Error
                    path: 'error/errors'
                    message: 'message'
            """
                )
            )

            if not result.get("async") and method.response.get("$ref") == "Operation":
                operation = api.get_schema_type_definition("Operation")
                operation_properties = operation.get("properties", {})
                if "done" in operation_properties:
                    result.update(new_style_async)
                elif "targetLink" in operation_properties:
                    result.update(old_style_async)
                else:
                    logging.warning("no async operation definition added")

        def add_create_link():
            id_name = type_name[0].lower() + type_name[1:] + "Id"
            if (
                id_name not in method.parameters
                and "name" not in type_definition.properties
            ):
                return

            result["import_format"] = [result["base_url"] + "/{{name}}"]

            query_parameters = {}
            parameters = []
            readable_name = parameter_camel_case_to_snake_case(type_name).replace(
                "_", " "
            )
            for name, value in method.parameters.items():
                if not value.is_required:
                    continue

                if name == id_name:
                    parameter = self.create_magic_module_field(
                        api, "name", type_definition.properties["name"]
                    )
                    parameter[
                        "description"
                    ] = f"A user-defined name which uniquely identifies a {readable_name}."
                    parameter["url_param_only"] = True
                    parameters.append(parameter)
                    if value.get("location") == "query":
                        query_parameters[name] = "{{name}}"
                elif name == "parent":
                    parameter = self.create_magic_module_field(api, "location", value)
                    parameter["url_param_only"] = True
                    parameter["description"] = f"the location of the {readable_name}."
                    if value.get("location") == "query":
                        query_parameters[name] = "{{location}}"

                    parameters.append(parameter)
                elif name == "updateMask":
                    continue
                else:
                    parameter = self.create_magic_module_field(
                        api, parameter_camel_case_to_snake_case(name), value
                    )
                    if value.get("location") == "query":
                        query_parameters[name] = (
                            "{{" + parameter_camel_case_to_snake_case(name) + "}}"
                        )
                    parameters.append(parameter)

            if query_parameters:
                result["create_url"] = (
                    result["base_url"]
                    + "/?"
                    + "&".join(
                        map(lambda q: f"{q[0]}={q[1]}", query_parameters.items())
                    )
                )
            if parameters:
                result["parameters"] = parameters

        add_base_url()
        add_self_link()
        add_update_verb()
        add_create_link()
        add_async_operation()

        return result

    def create_magic_module_resource(
        self, api: APIMetaData, resource_name: str, type_name: str
    ) -> Resource:
        """
        Creates a magic module resource definition for the type `type_name` of the `resource_name`
        in the `api`.
        """
        resource_definition = api.get_resource_definition(resource_name)
        create_method = resource_definition.get_insert_or_create_method()
        type_definition = create_method.request
        schema_type_name = type_definition.get("$ref", type_name)
        if schema_type_name and schema_type_name != type_name:
            logging.info(
                "schema type name in create method is %s, not %s",
                schema_type_name,
                type_name,
            )

        properties = self.generate_magic_module_resource_properties(
            api, resource_name, type_name, schema_type_name
        )
        result = Resource(properties)

        result.update(self.create_magic_module_field(api, None, type_definition))
        if any(
            filter(
                lambda p: p.get("name") in ["name", "selfLink"],
                result.get("parameters", []),
            )
        ):
            result["properties"] = list(
                filter(
                    lambda p: p.get("name") not in ["name", "selfLink"],
                    result["properties"],
                )
            )
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
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s: %(message)s"
    )


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
    product_definition_file = Path(product_directory).joinpath("product.yaml")
    if not product_definition_file.exists():
        click.echo(
            f"'{product_directory} is not a magic module product directory",
            err=True,
        )

    product_definition = Product.load(product_definition_file)
    updater = Scaffolder()
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
    "--inplace",
    is_flag=True,
    default=False,
    required=False,
    help="update the resource definition file",
)
def update(resource_file: str, inplace: bool):
    """
    updates the resource definition in the resource-file to match the latest API specification.
    """
    product_definition_file = Path(resource_file).parent.joinpath("product.yaml")
    if not product_definition_file.exists():
        click.echo(
            f"magic module product definition file '{product_definition_file} not found",
            err=True,
        )

    product_definition = Product.load(product_definition_file)

    existing: Optional[Resource] = None
    preamble: str = ""
    try:
        existing, preamble = Resource.load(resource_file)
    except ValueError as error:
        click.echo(str(error), err=True)
        exit(1)

    type_name = existing["name"]
    resource_name = existing["base_url"].split("/")[-1]

    updater = Scaffolder()

    for provider_version, api_id in product_definition.get_api_ids():
        api = APIMetaData.load(api_id)
        defined = updater.create_magic_module_resource(api, resource_name, type_name)
        Resource.merge_resources(existing, defined, provider_version)

    if inplace:
        with open(resource_file, "w") as file:
            file.write(preamble)
            yaml.dump(existing, file)
    else:
        sys.stdout.write(preamble)
        yaml.dump(existing, sys.stdout)
