"""Agente de Contexto (interno): lê conversas ENCERRADAS e produz sinais → asserções → propostas.

Nunca aplica nada — só o próprio usuário confirma (regra-estrela de 21_context; T22–T24, C22a–c
são do banco). O LLM extrai, não decide; referencia mensagens por seq, nunca UUID.
"""
