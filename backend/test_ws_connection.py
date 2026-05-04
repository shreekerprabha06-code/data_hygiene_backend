import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8005/ws"

    print(f"Attempting to connect to {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("[OK] Connected successfully!")

            # Send a heartbeat message
            await websocket.send("ping")
            print("[OK] Sent ping message")

            # Wait for broadcast messages (with timeout)
            async def receive_messages():
                try:
                    while True:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        data = json.loads(message)
                        print(f"\n[OK] Received message:")
                        print(json.dumps(data, indent=2))
                except asyncio.TimeoutError:
                    print("\n[OK] No more messages received (timeout)")

            await receive_messages()

    except ConnectionRefusedError:
        print("[ERROR] Connection refused - server may not be running")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[ERROR] Connection closed: {e}")
    except Exception as e:
        print(f"[ERROR] Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())
