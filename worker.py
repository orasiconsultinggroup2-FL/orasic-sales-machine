import asyncio
async def worker_loop():
    while True:
        print("Worker running")
        await asyncio.sleep(1800)
if __name__ == "__main__":
    asyncio.run(worker_loop())
