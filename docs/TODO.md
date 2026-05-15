# TODO proiect

## Matei – Proxy server

- [ ] pornire proxy pe portul 9000
- [ ] citire mesaje JSON line-delimited
- [ ] `proxy_ping`
- [ ] `proxy_read_file`
- [ ] generare `request_id`
- [ ] mapare `request_id -> client`
- [ ] forward catre destination
- [ ] tratare `DESTINATION_UNAVAILABLE`
- [ ] cleanup mapari

## Sabina – Destination server + Docker

- [ ] pornire destination pe portul 9101
- [ ] citire `FORWARDED_REQUEST`
- [ ] raspuns `DESTINATION_RESPONSE`
- [ ] `echo`
- [ ] `uppercase`
- [ ] `delay_echo`
- [ ] Dockerfile destination
- [ ] Dockerfile proxy
- [ ] docker-compose cu proxy + destination

## Valter – Client demo + README

- [ ] client demo conectat la proxy
- [ ] scenariu cu doi clienti logici
- [ ] demo out-of-order
- [ ] demo `proxy_read_file`
- [ ] demo target invalid
- [ ] README actualizat cu pasii reali