"""In-memory backend used when config.DEMO_MODE is on.

Lets the whole app run with zero AWS credentials by standing in for the
DynamoDB tables and S3 object store. Data lives only for the process lifetime.
"""
import copy


class InMemoryTable:
    """Mimics the subset of the boto3 DynamoDB Table API that db.py uses."""

    def __init__(self):
        self._items = {}

    def put_item(self, Item):
        self._items[Item["id"]] = copy.deepcopy(Item)
        return {}

    def delete_item(self, Key):
        self._items.pop(Key["id"], None)
        return {}

    def get_item(self, Key):
        item = self._items.get(Key["id"])
        return {"Item": copy.deepcopy(item)} if item else {}

    def scan(self, ExclusiveStartKey=None):
        return {"Items": [copy.deepcopy(v) for v in self._items.values()]}

    def update_item(
        self,
        Key,
        UpdateExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
        ReturnValues="ALL_NEW",
    ):
        item = self._items.get(Key["id"], {"id": Key["id"]})
        for assign in UpdateExpression[len("SET "):].split(","):
            name_alias, value_alias = [p.strip() for p in assign.split("=")]
            field = ExpressionAttributeNames[name_alias]
            item[field] = copy.deepcopy(ExpressionAttributeValues[value_alias])
        self._items[Key["id"]] = item
        return {"Attributes": copy.deepcopy(item)}


# Singletons shared across the process.
CONTRACTS = InMemoryTable()
DOCUMENTS = InMemoryTable()
MESSAGES = InMemoryTable()

# key -> (bytes, content_type)
BLOBS = {}
