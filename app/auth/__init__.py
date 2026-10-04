"""Autenticação própria (F7): senha com scrypt e sessão opaca em identity.sessions.

O browser só conhece um token aleatório em cookie httpOnly; o banco só conhece o sha256 dele.
`deps.identidade` é o único consumidor: cookie → identity.autenticar_sessao → (user_id, scope_id).
"""
