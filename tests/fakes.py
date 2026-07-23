"""Minimal in-memory stand-in for a boto3 DynamoDB Table.

Supports the operations db.py uses: put_item, get_item, scan, update_item
(SET only, with expression attribute name/value aliases), delete_item.
"""
import copy


class FakeTable:
    def __init__(self):
        self._items = {}

    # --- writes ----------------------------------------------------------
    def put_item(self, Item):
        self._items[Item["id"]] = copy.deepcopy(Item)
        return {}

    def delete_item(self, Key):
        self._items.pop(Key["id"], None)
        return {}

    def update_item(
        self,
        Key,
        UpdateExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
        ReturnValues="ALL_NEW",
    ):
        item = self._items.get(Key["id"], {"id": Key["id"]})
        assignments = UpdateExpression[len("SET "):].split(",")
        for assign in assignments:
            name_alias, value_alias = [p.strip() for p in assign.split("=")]
            field = ExpressionAttributeNames[name_alias]
            item[field] = copy.deepcopy(ExpressionAttributeValues[value_alias])
        self._items[Key["id"]] = item
        return {"Attributes": copy.deepcopy(item)}

    # --- reads -----------------------------------------------------------
    def get_item(self, Key):
        item = self._items.get(Key["id"])
        return {"Item": copy.deepcopy(item)} if item else {}

    def scan(self, ExclusiveStartKey=None):
        return {"Items": [copy.deepcopy(v) for v in self._items.values()]}
