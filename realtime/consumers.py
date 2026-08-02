"""EventsConsumer — the one multiplexed socket (§3.5/§D7).

Session-authenticated at connect (reject anonymous); client protocol
{action: subscribe|unsubscribe, topics: [...]}; topic string == group name.
"""
import json

from channels.generic.websocket import AsyncWebsocketConsumer

from .authorize import authorize_topic


class EventsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.topics = set()
        await self.accept()

    async def disconnect(self, code):
        for topic in getattr(self, "topics", set()):
            await self.channel_layer.group_discard(topic, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            msg = json.loads(text_data)
            action, topics = msg["action"], msg["topics"]
        except (ValueError, KeyError, TypeError):
            await self.send(json.dumps({"error": "bad message"}))
            return

        user = self.scope["user"]
        if action == "subscribe":
            for topic in topics:
                if authorize_topic(user, topic):
                    self.topics.add(topic)
                    await self.channel_layer.group_add(topic, self.channel_name)
                    await self.send(json.dumps({"subscribed": topic}))
                else:
                    await self.send(json.dumps({"denied": topic}))
        elif action == "unsubscribe":
            for topic in topics:
                self.topics.discard(topic)
                await self.channel_layer.group_discard(topic, self.channel_name)

    async def topic_event(self, message):
        await self.send(
            json.dumps(
                {"topic": message["topic"], "seq": message["seq"], "event": message["event"]}
            )
        )
