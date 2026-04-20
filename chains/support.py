from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

class SupportEmail(BaseModel):
    subject: str = Field(description = "")
    body: str = Field(description = "")

support_prompt = ChatPromptTemplate.from_messages([
    ("system",""),
    ("human","")
    ])

def build_support_chain():
    llm = ChatOpenAI(model="",
                      api_key="",
                       temperature=0.4)
    return support_prompt | llm.with_structured_output(SupportEmail)


