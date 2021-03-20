from playhouse.sqlite_ext import SqliteExtDatabase, Model, TextField, JSONField, BooleanField, TimestampField, FloatField
import os

db_name = 'Orders.db'
sqlite_db = SqliteExtDatabase(database=db_name, pragmas={'journal_mode': 'wal'})


class BaseModel(Model):

    class Meta:
        database = sqlite_db


class Orders(BaseModel):

    id = TextField()
    params = JSONField()
    long = BooleanField()
    short = BooleanField()
    time = TimestampField()
    failed = BooleanField()
    price = FloatField()
    track_price = FloatField()
    status = TextField()


if not os.path.isfile(db_name):
    Orders.create_table()
