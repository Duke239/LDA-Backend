import os
from motor.motor_asyncio import AsyncIOMotorClient

async def connect_to_mongo(app):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "lda_timetracking")]
    app.state.mongo_client = client
    app.state.db = db

async def close_mongo_connection(app):
    app.state.mongo_client.close()
