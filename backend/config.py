from pydantic import BaseModel, field_validator
from typing import Optional

class OllamaConfig(BaseModel):
    host: str
    model_name: str

class AppConfig(BaseModel):
    main_model: Optional[OllamaConfig] = None
    embedding_model: Optional[OllamaConfig] = None
    
    # RAG Workflow Mode: Determines the architectural graph structure.
    # Options:
    # 1. "fused" (Default): Uses a single 'Planner' node for routing/rewriting/planning. 
    #    - Fastest (1 LLM call vs 3). 
    #    - Requires a smarter model (e.g., 72B).
    # 2. "modular" (Legacy): Uses separate Router -> Rewriter -> Retriever nodes.
    #    - Slower (3 sequential LLM calls).
    #    - More stable for smaller models (e.g., 7B) that struggle with complex instructions.
    rag_workflow: str = "fused"

    @field_validator("rag_workflow")
    @classmethod
    def validate_workflow(cls, v):
        v = v.lower()
        if v not in ["fused", "modular"]:
            return "modular"  # Default to Safe Mode if invalid
        return v

    @property
    def is_configured(self) -> bool:
        return self.main_model is not None and self.embedding_model is not None

import os

# Singleton instance
_runtime_config = AppConfig()

def get_config() -> AppConfig:
    # If not configured in memory, check env vars (in case of uvicorn worker)
    if not _runtime_config.is_configured:
        main_host = os.getenv("RAG_MAIN_HOST")
        main_model = os.getenv("RAG_MAIN_MODEL")
        embed_host = os.getenv("RAG_EMBED_HOST")
        embed_model = os.getenv("RAG_EMBED_MODEL")

       

#APP_BASE_URL=https://askme.ipr.res.in:8000
#SAML_IDP_ENTITY_ID=http://adfs.ipr.res.in/adfs/services/trust
#SAML_IDP_SSO_URL=https://adfs.ipr.res.in/adfs/ls
#SAML_IDP_SLO_URL= https://adfs.ipr.res.in/adfs/ls/
#SAML_IDP_X509="MIIE2jCCAsKgAwIBAgIQFZeVW3ajxbdBbYLe4jRl8zANBgkqhkiG9w0BAQsFADApMScwJQYDVQQDEx5BREZTIFNpZ25pbmcgLSBhZGZzLmlwci5yZXMuaW4wHhcNMjUwMzEwMTYxNjEwWhcNMjYwMzEwMTYxNjEwWjApMScwJQYDVQQDEx5BREZTIFNpZ25pbmcgLSBhZGZzLmlwci5yZXMuaW4wggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIKAoICAQDnbOkJ0wqw6jhrktEsUIv/LdGBSpWRFCcIdRCUSc7maR6cMokv4ZU6OM4o7JHBXCZewDYe0nOzQkaSsSB1vksGj0OFn4w+tuR8f9f768poL521ldtftVoECOoHL4SR/B6MKnSsYrbHf6awomz5ONwz5vXUAngrZFE9GiZXqNyL3DVVHE0ujJ0quXUcUmnkw2o+A0yiuEC0bQXtt+BqyRcB6UBjjXiTlLKQqdCKbnp/NTynh/4CrFMHilzaQDjJ35evY72D06zwxRCumtEScFLaFSvwTQ9Jr9WQQyCNrY95SBJjJtjdxpfGA+fDeQVdp6l3GHKZtq+zrgtXHKccRRtUq2TroM7/eCh0Uw+X3MzYxHYWWRWV0M5YYAy88EKgyVNkst9oqhD2tXseqLLZptsfm2I+6QjLqKmhbUL9AqqjPYxryXM9JpcS9L6cad9k0IM3/9ggjyru8zzx9NPz52+xuKKWfoW3ZLmtjkZQJ42vcccCbeDgoqEx618cUcR8Oqo5CD4NaQGMrMc4OKbE4IPfR8p3JmXx+gIOQ96ffXT2ZJIB0wZny39c/rxmpD2MwfNeuS95hGpXkvPwUm3v8xLbpciGO6EW/qOfqRSszt3brtLDEfwsOvdCjWGPCrSK6jpVmp+B7wOzbwZGUnqeOeR+Sg+Rl7v1NTq6ujrIAvY/rQIDAQABMA0GCSqGSIb3DQEBCwUAA4ICAQCcRg2FoDi3pm3h68DAl5XVj24owedrNUboo53vaFZ1nfG7tjzj2HU7TClToqXil29CgwFoGJv1yeJeXukkWA9lLI57JAtf5AbQ+Qh41KTcXevPr1XlgUMnVB91eXtzAllU7kdyj4ty126PhllTXOd1K10MmscofWtTdWEk3Yvxy2dZcz9SFGmEF5qrVmGuH/+DPA4+8OpHFLIHp3i4AWO35E3UctUfnY5fzEEZ06aU29A4tLFZl66d9rgmN5tpicM45vOi08WtVGzyUtHIkWn9vNqyS+52/0OVqKfV4MtJeeN1I7eVehi9O0QrPa1ZqvRTyifMVnxWvmwh9JkUQeRr95PxrWcGAo8zFkyoI0gSqqynalZWzHdvw/ARyvoyso43+Z0JEfXRClbzO2u+2S4VQaSJMTn7r4t9ifAXBXdPP4IY9Win3bxGb0oYqUZc7rLH6aK+amE7nRm/p5Lca1QgP25t3OFOpG+rcQGoOs+55D5hB2hwp4FKXvTbDuAInaTGQufv3MKibdyhXweKHZ/E3h8tQGqZ63qmxhHCxjksW3pJ9OFgYRbIGpciuiAhDMLJx50KVLBGVdNCvCZ0S/jxJuXSWoTZpEPrGyEdDBKLTM+smN+TRvu9dI1ikoHwiWECkB53YV9wmxm6Sz5Dv8CL8eMaDSyVN6oESMID9FmdhA=="
#JWT_SECRET=replace-with-a-strong-secret
#JWT_EXP_SECONDS=3600
#SAML_DEBUG=true






        if main_host and main_model and embed_host and embed_model:
            _runtime_config.main_model = OllamaConfig(host=main_host, model_name=main_model)
            _runtime_config.embedding_model = OllamaConfig(host=embed_host, model_name=embed_model)
            
    return _runtime_config

def set_main_model(host: str, model: str):
    _runtime_config.main_model = OllamaConfig(host=host, model_name=model)

def set_embedding_model(host: str, model: str):
    _runtime_config.embedding_model = OllamaConfig(host=host, model_name=model)
