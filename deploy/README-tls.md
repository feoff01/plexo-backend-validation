# Ligar TLS entre a Vercel e a EC2 — a ordem importa

## O problema, em uma frase

O `next.config.ts` reescreve `/api/*` para `http://<ip-da-ec2>`. A perna navegador→Vercel é TLS;
a perna **Vercel→EC2 atravessa a internet pública em claro**, carregando o corpo de
`POST /auth/login` com a senha, o `Cookie: plx_sessao` de toda chamada seguinte, e as respostas de
`/carteira` e `/perfil` com posições, renda, dívidas e objetivos do cliente.

`COOKIE_SECURE=true` não protege disso: a exposição é servidor-a-servidor, e o cookie viaja no
salto que ninguém estava olhando. O comentário antigo do `Caddyfile` ("o navegador nunca fala
HTTP") descrevia corretamente a primeira perna e silenciava sobre a segunda.

## O que já está feito no repositório

O `Caddyfile` serve **as duas coisas ao mesmo tempo**: HTTP na 80 (que é por onde a Vercel fala
hoje) e HTTPS na 443. Isso é deliberado — a mudança é aditiva, e **nada que funciona hoje para de
funcionar quando você faz o deploy**. O `docker-compose.yml` publica a 443, e o `deploy.sh` roda
`caddy validate` num contêiner descartável antes de qualquer coisa subir.

O certificado sai **antes** de a 443 estar aberta: `disable_tlsalpn_challenge` força o desafio
HTTP-01, que roda na porta 80. `sslip.io` está na Public Suffix List, então a Let's Encrypt emite
para `3-236-177-183.sslip.io` normalmente.

## Os quatro passos, nesta ordem

Inverter 2 e 3 derruba a API: a Vercel receberia um 308 para uma porta que não responde.

**1. Deploy (seguro a qualquer momento).**
```
bash deploy/deploy.sh
```
O Caddy sobe servindo HTTP e HTTPS, e pede o certificado. Confira que ele saiu:
```
ssh <ec2> 'cd /srv/plexo && docker compose logs caddy --tail 40 | grep -i "certificate obtained"'
```
Se não saiu, **pare aqui** — a 80 precisa estar aberta e o nome precisa resolver para o IP.

**2. Abrir a 443 no Security Group da EC2** (console AWS → EC2 → Security Groups → Inbound rules
→ Add rule: HTTPS, TCP 443, `0.0.0.0/0`). Só depois disso:
```
curl -fsS https://3-236-177-183.sslip.io/health
```
tem de responder de fora.

**3. Apontar a Vercel para HTTPS.** Variável de ambiente do projeto do frontend:
```
API_PROXY_TARGET = https://3-236-177-183.sslip.io
```
Redeploy do frontend. **A partir daqui o salto Vercel→EC2 está cifrado** — é este passo que fecha
o buraco; os outros só o tornam possível.

**4. Remover o HTTP** (opcional, depois de confirmar que tudo passa pela 443). No `Caddyfile`,
troque o bloco `http://...:80` por um redirecionamento:
```
http://3.236.177.183:80, http://3-236-177-183.sslip.io:80 {
	redir https://3-236-177-183.sslip.io{uri} permanent
}
```
Mantenha a 80 aberta no Security Group: é por ela que a Let's Encrypt renova o certificado a cada
60 dias, e fechá-la faria o certificado expirar em silêncio.

## O que continua imperfeito, e vale saber

- **O IP registrado passa a ser o da Vercel.** Com todo o tráfego chegando pelo proxy, o peer que
  o Caddy vê é o egress da Vercel, não o navegador do cliente. Isso é honesto (é mesmo quem falou
  com a EC2), mas degrada o limite por IP de `login_max_falhas_ip`: todos os clientes viram um IP
  só. A saída certa é a Vercel encaminhar o IP do cliente e o Caddy passar a confiar nela via
  `trusted_proxies` — o que exige a lista de egress da Vercel, que muda. Fica registrado como
  pendência, e **não** como algo que este arquivo resolveu.
- **`3-236-177-183.sslip.io` prende o certificado ao IP.** Trocar a instância troca o nome e o
  certificado. Um domínio próprio resolve isso e é o caminho quando houver um.
