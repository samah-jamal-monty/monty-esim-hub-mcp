import asyncio

from config.utils import esim_hub_service_instance, send_email

service = esim_hub_service_instance()


send_email("test","<h1>Test</h1>","samah.jamal.monty@gmail.com")