import asyncio
from app.db.mongo import mongo_client

async def main():
    mongo_client.connect()
    if mongo_client.db is not None:
        count = await mongo_client.db["repositories"].count_documents({})
        print(f"MongoDB Atlas 'repositories' collection count: {count}")
    else:
        print("MongoDB Atlas not connected.")
    mongo_client.close()

if __name__ == "__main__":
    asyncio.run(main())
