import re
from functools import lru_cache
from io import StringIO
from textwrap import TextWrapper
from typing import Set, Optional, Dict

import requests


@lru_cache
def all_available_apis() -> Dict[str, dict]:
    """
    returns directory descriptions of all available APIs. The key is
    the api id, which consists of the name and version concatenate with a colon.
    """
    response = requests.get("https://www.googleapis.com/discovery/v1/apis")
    if response.status_code != 200:
        raise ValueError(
            f"failed to retrieve API documents, {response.status_code}, {response.text}"
        )

    return {a["id"]: a for a in response.json()["items"]}


def all_available_versions_of(api_id: str) -> [str]:
    """
    returns all versions of associated with the api `api_id`.
    """
    name = api_id.split(":")[0]
    return list(
        map(
            lambda i: i.split(":")[-1],
            filter(lambda i: i.startswith(name + ":"), all_available_apis().keys()),
        )
    )


def all_available_api_names() -> set[str]:
    """
    returns all available api names.
    """
    return set(map(lambda i: i.split(":")[0], all_available_apis().keys()))


def all_available_api_ids() -> Set[str]:
    """
    returns all available api ids.
    """
    return set(list(all_available_apis().keys()))


class SchemaTypeDefinition(dict):
    """
    represents a JSON schema type definition.
    """

    def __init__(self, other: dict):
        super().__init__()
        self.update(other)

    @property
    def is_resource_ref(self) -> re.Match:
        """
        Returns the Match object if this type represents a google cloud platform resource reference.
        """
        return (
            re.search(
                r"URL\s+referring\s+to\s+an?\s+([^\s]+)\s+",
                self.get("description", ""),
                re.IGNORECASE,
            )
            if self.get("type", "") == "string"
            else None
        )

    @property
    def is_output_only(self) -> bool:
        description = self.get("description", "").lower()
        return description.startswith("output only") or "[output only]" in description

    @property
    def is_input_only(self) -> bool:
        return "@inputonly" in self.get("description", "").lower()

    @property
    def is_deprecated(self) -> bool:
        return "deprecated" in self.get("description", "").lower()

    @property
    def is_required(self) -> bool:
        return self.get("description", "").lower().startswith("required.")

    @property
    def value_type(self) -> str:
        return self.get("type")

    @property
    def value_format(self) -> str:
        return self.get("format", "")

    @property
    def kind(self) -> Optional[str]:
        return self.get("properties", {}).get("kind", {}).get("default")

    @property
    def properties(self) -> Dict[str, "SchemaTypeDefinition"]:
        return {
            name: SchemaTypeDefinition(definition)
            for name, definition in self.get("properties", {}).items()
        }

    @property
    def description(self) -> str:
        writer = StringIO()
        wrapper = TextWrapper(width=72, break_long_words=False, break_on_hyphens=False)
        description = self.get("description", "")
        if description:
            writer.write("\n".join(wrapper.wrap(description)))

        descriptions = self.get("enumDescriptions", [])
        if descriptions:
            if writer.tell() != 0:
                writer.write("\n")
            writer.write("The possible values are:\n")
            for i, enum_value in enumerate(self.get("enum", [])):
                enum_description = descriptions[i] if i < len(descriptions) else ""
                if not enum_description:
                    continue
                wrapper.subsequent_indent = " " * (len(enum_value) + 5)
                writer.write("\n")
                writer.write(
                    "\n".join(wrapper.wrap(f"* `{enum_value}`: {enum_description}"))
                )
                writer.write("\n")
        return writer.getvalue()


class SchemaMethodDefinition(dict):
    def __init__(self, other: dict):
        super().__init__()
        self.update(other)

    @property
    def flat_path(self) -> str:
        """
        the path for the operation
        """
        return self.get("flatPath")

    @property
    def request(self) -> SchemaTypeDefinition:
        """
        the schema definition of the request
        """
        return SchemaTypeDefinition(self.get("request"))

    @property
    def response(self) -> SchemaTypeDefinition:
        """
        the schema definition of the response
        """
        return SchemaTypeDefinition(self.get("response"))

    @property
    def parameters(self) -> Dict[str, "SchemaTypeDefinition"]:
        return {
            name: SchemaTypeDefinition(definition)
            for name, definition in self.get("parameters", {}).items()
        }


class SchemaResourceDefinition(dict):
    def __init__(self, resource_name: str, other: dict):
        super().__init__()
        self.resource_name = resource_name
        self.update(other)

    @property
    def methods(self) -> dict[SchemaMethodDefinition]:
        return {
            name: SchemaMethodDefinition(value)
            for name, value in self.get("methods", {}).items()
        }

    def get_insert_or_create_method(self) -> SchemaMethodDefinition:
        insert_definition = self.methods.get("insert", self.methods.get("create"))
        if not insert_definition:
            raise ValueError(
                f"No insert or create method found on resource {self.resource_name}"
            )
        return SchemaMethodDefinition(insert_definition)


class APIMetaData:
    @lru_cache
    def __init__(self, api_id: str):
        self.api_id = api_id
        self.api_name, self.api_version = api_id.split(":")
        self.document = {}

    @staticmethod
    @lru_cache
    def load(api_id: str) -> "APIMetaData":
        if api_id not in all_available_apis():
            raise ValueError(
                f"invalid api id: {api_id}, available versions are: {all_available_versions_of(api_id)}"
            )

        api = all_available_apis()[api_id]
        response = requests.get(api["discoveryRestUrl"])
        if response.status_code != 200:
            raise ValueError(
                f'failed to retrieve metadata from {api["discoveryRestUrl"]}, {response.text}'
            )
        result = APIMetaData(api_id)
        result.document = response.json()
        return result

    def get_schema_type_definition(self, type_name: str) -> SchemaTypeDefinition:
        result = self.document.get("schemas", {}).get(type_name)
        if not result:
            raise ValueError(
                f"no type {type_name} defined in schema for api {self.api_id}"
            )
        return SchemaTypeDefinition(result)

    def get_resource_definition(self, resource_name: str) -> SchemaResourceDefinition:
        legacy = self.document.get("resources", {})
        project_level = (
            legacy.get("projects", {})
            .get("resources", {})
            .get("locations", {})
            .get("resources", {})
        )
        org_level = legacy.get("organizations", {}).get("resources", {})

        if resource_name in org_level:
            return SchemaResourceDefinition(resource_name, org_level[resource_name])
        elif resource_name in project_level:
            return SchemaResourceDefinition(resource_name, project_level[resource_name])
        elif resource_name in legacy:
            return SchemaResourceDefinition(resource_name, legacy[resource_name])
        else:
            names = (
                set(legacy.keys()).union(org_level.keys()).union(project_level.keys())
            )
            raise ValueError(
                f"resource {resource_name} not found, available resources {', '.join(names)}"
            )
