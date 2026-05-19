import google.auth
from google.cloud import pubsub_v1

_, _PROJECT_ID = google.auth.default()


def publish(topic: str, data: str):
    client = pubsub_v1.PublisherClient()
    topic_path = client.topic_path(_PROJECT_ID, topic)
    future = client.publish(topic_path, data=data.encode())
    future.result()
