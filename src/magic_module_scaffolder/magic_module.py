import logging
import re
from pathlib import Path
from typing import Optional, Generator, Union

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.tag import Tag

from magic_module_scaffolder.yaml import yaml

_api_url_pattern = re.compile(r"https:\/\/(?P<name>[^\.]*)\.googleapis\.com\/.*")


class Product(CommentedMap):
    def __init__(self, value: CommentedMap):
        super().__init__()
        if value.tag.value != "!ruby/object:Api::Product":
            raise ValueError("value is not a magic module product definition")
        self.value = value

    @staticmethod
    def load(path: Path):
        with open(path, "r") as file:
            return Product(yaml.load(file))

    def get_api_id(self, version_name: str) -> Optional[str]:
        assert version_name in ["beta", "ga"]

        version = next(
            filter(lambda v: v["name"] == version_name, self.value.get("versions", [])),
            None,
        )
        if not version:
            return None

        base_url = version["base_url"]
        match = _api_url_pattern.fullmatch(base_url)
        if not match:
            raise ValueError(
                f"{base_url} does not match the expected google cloud platform API url"
            )

        name = match.group("name")
        version = base_url.strip("/").split("/")[-1]
        return f"{name}:{version}"

    def get_api_ids(self) -> Generator:
        """
        returns the available provider version name and associated api id.
        """
        for name in ["ga", "beta"]:
            api_id = self.get_api_id(name)
            if api_id:
                yield name, api_id


@yaml.register_class
class Field(CommentedMap):
    """
    represents a Magic Module Field definition.
    """

    def __init__(self, tag):
        super().__init__(self)
        self.yaml_set_ctag(Tag(suffix=tag))

    @staticmethod
    def create(item: Union[dict, str]) -> "Field":
        if isinstance(item, str):
            if item.startswith("Api::Type::"):
                result = Field(f"!ruby/object:{item}")
                return result
            else:
                raise ValueError(
                    "cannot create a field from a string which is not an Api::Type name"
                )

        tag = item.pop("type", None)
        if tag:
            result = Field(f"!ruby/object:{tag}" if tag else "")
            result.update(item)
        else:
            result = item
        return result

    @staticmethod
    def merge_fields(
        existing: Union["Resource", "Field", dict, str],
        defined: Union["Resource", "Field", dict, str],
        path: [str],
        provider_version: str,
    ):
        """
        merges the fields from the `defined` into `existing` field definition.
        """
        assert existing is not None
        assert defined is not None
        assert provider_version in ["ga", "beta"]

        if isinstance(existing, str):
            if existing.startswith("Api::Type::"):
                result = Field(f"!ruby/object:{existing}")
                return result
            else:
                raise ValueError(
                    "cannot create a field from a string which is not an Api::Type name"
                )

        existing_name = existing.get("api_name", existing.get("name", ""))
        defined_name = defined.get("api_name", defined.get("name", ""))

        if defined_name != existing_name:
            logging.warning(
                'mismatch in field name %s: expected "%s" defined "%s"',
                ".".join(path),
                existing_name,
                defined_name,
            )
        path = path + [existing_name]

        if "properties" in existing and "properties" in defined:
            defined_properties = {p["name"]: p for p in defined.get("properties", [])}
            existing_properties = {
                p.get("api_name", p["name"]): p for p in existing.get("properties", [])
            }
            new_properties_names = (
                defined_properties.keys() - existing_properties.keys()
            )
            undefined_property_names = (
                existing_properties.keys() - defined_properties.keys()
            )

            for name in set(undefined_property_names):
                if len(path) == 1 and name == "name":
                    # this occurs in the cloud Run v2 interface where name is clearly used in the API
                    # but not in the api definition.
                    logging.warning(
                        "the field 'name' is missing from the API definition, but keeping it in the as it is a special name")
                    undefined_property_names.remove("name")
                    continue

                if provider_version == "ga":
                    undefined_property_names.remove(name)
                    if existing_properties[name].get("min_version", "ga") != "beta":
                        existing_properties[name]["min_version"] = "beta"
                        logging.info(
                            "marking field '%s' from definition of '%s' as beta",
                            name,
                            ".".join(path),
                        )

                else:
                    logging.warning(
                        "removing field '%s' from definition of '%s'", name, ".".join(path)
                    )

            properties = list(
                filter(
                    lambda p: p.get("api_name", p["name"])
                    not in undefined_property_names,
                    existing["properties"],
                )
            )

            for name in new_properties_names:
                logging.info(
                    "adding %s as %s field to definition of %s",
                    name,
                    provider_version,
                    ".".join(path),
                )
                if provider_version == "beta":
                    defined_properties[name]["min_version"] = "beta"
                properties.append(defined_properties[name])

            existing["properties"] = properties

            for i, current_property in enumerate(existing["properties"]):
                property_name = current_property.get(
                    "api_name", current_property["name"]
                )
                if property_name in defined_properties:
                    defined_property = defined_properties.get(property_name)
                    Field.merge_fields(
                        current_property, defined_property, path, provider_version
                    )
        else:
            if defined.tag.value != existing.tag.value:
                logging.warning(
                    "mismatch of type on field %s, existing tag %s and defined %s",
                    ".".join(path),
                    existing.tag.value,
                    defined.tag.value,
                )
                return
            if defined.tag.value == "!ruby/object:Api::Type::Array":
                Field.merge_fields(
                    existing["item_type"], defined["item_type"], path, provider_version
                )


class Resource(CommentedMap):
    """
    represents a Magic Module resource definition.
    """

    def __init__(self, other: dict):
        super().__init__(self)
        self.yaml_set_ctag(Tag(suffix="!ruby/object:Api::Resource"))
        self.update(other)
        if isinstance(other, CommentedMap):
            self.copy_attributes(other)

    @staticmethod
    def load(path: str) -> ("Resource", str):

        with open(path, "r") as file:
            content = file.read()
            result = yaml.load(content)

        preamble = Resource.extract_preamble_comment(content)

        if not result:
            raise ValueError(
                f"{path} is empty"
            )

        if (
            not isinstance(result, CommentedMap)
            or result.tag.value != "!ruby/object:Api::Resource"
        ):
            raise ValueError(
                f"{path} does not contain a Magic Module object:Api::Resource"
            )

        resource = Resource(result)
        return resource, preamble

    @staticmethod
    def extract_preamble_comment(content):
        """
        extracts the preamble comment of a yaml document. it was too hard to get ruamel.yaml to comply :-p
        """
        line = ""
        line_number = 0
        lines = content.splitlines(keepends=True)
        for line_number, line in enumerate(lines):
            if not line.startswith("#") and line != "\n":
                break
        comment = "".join(lines[:line_number])
        if line.startswith("--- "):
            comment = comment + "--- "
        elif line == "---\n":
            comment = comment + "---\n"

        return comment

    @staticmethod
    def merge_resources(
        existing: Union["Resource"], defined: Union["Resource"], provider_version: str
    ):
        """
        merges the `defined` resource definition into the `existing` resource definition,
        """
        assert existing is not None
        assert defined is not None
        assert provider_version in ["ga", "beta"]

        Field.merge_fields(existing, defined, [], provider_version)


yaml.representer.add_representer(Resource, RoundTripRepresenter.represent_dict)
yaml.representer.add_representer(Field, RoundTripRepresenter.represent_dict)
yaml.representer.add_representer(Product, RoundTripRepresenter.represent_dict)
