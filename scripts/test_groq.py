import sys, os, json
sys.path.insert(0, 'c:/Layer10')
os.chdir('c:/Layer10')

from extraction.llm_client import GroqClient

client = GroqClient()
prompt = 'Extract the following text into JSON format with keys "name" and "age": Bob is 42.'
result = client.extract(prompt)
print('Groq SDK Test Result:', json.dumps(result))
