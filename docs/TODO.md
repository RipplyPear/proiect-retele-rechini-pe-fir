# TODO proiect

## Matei – Proxy server

- [x] pornire proxy pe portul 9000
- [x] citire mesaje JSON line-delimited
- [x] `proxy_ping`
- [x] `proxy_read_file`
- [x] generare `request_id`
- [x] mapare `request_id -> client`
- [x] forward catre destination
- [x] tratare `DESTINATION_UNAVAILABLE`
- [x] cleanup mapari

## Sabina – Destination server + Docker

- [x] pornire destination pe portul 9101
- [x] citire `FORWARDED_REQUEST`
- [x] raspuns `DESTINATION_RESPONSE`
- [x] `echo`
- [x] `uppercase`
- [x] `delay_echo`
- [x] Dockerfile destination
- [x] Dockerfile proxy
- [x] docker-compose cu proxy + destination

## Valter – Client demo + README

- [x] client demo conectat la proxy
- [x] scenariu cu doi clienti logici
- [x] demo out-of-order
- [x] demo `proxy_read_file`
- [x] demo target invalid
- [x] README actualizat cu pasii reali