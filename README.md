# Rechini pe fir – Proxy pentru intermedierea comunicatiei

Proiect la disciplina **Retele de Calculatoare**.

Echipa: **Rechini pe fir**

- Mincinoiu Dragos-Matei
- Ionescu Sabina
- Mihailescu Valter-Ioan

## 1. Descriere

Proiectul implementeaza o aplicatie distribuita de tip client-proxy-server.

Clientul nu comunica direct cu serverul destinatie. In schimb, clientul trimite cereri catre un server proxy. Proxy-ul genereaza un identificator unic pentru fiecare cerere, memoreaza asocierea dintre identificator si client, trimite cererea mai departe catre serverul destinatie, apoi livreaza raspunsul inapoi clientului corect.

Flux general:

```text
Client -> Proxy -> Destination Server -> Proxy -> Client
```

Proxy-ul poate raspunde si la cereri adresate lui direct, fara sa le trimita mai departe catre serverul destinatie.

## 2. Tehnologii folosite

* Python 3
* asyncio
* TCP sockets
* JSON line-delimited protocol
* Docker
* Docker Compose
* Wireshark pentru inspectarea traficului

## 3. Arhitectura

```text
+----------+        TCP/JSON        +--------------+        TCP/JSON        +--------------------+
| Client A | ---------------------> | Proxy Server | ---------------------> | Destination Server |
+----------+                        +--------------+                        +--------------------+
                                           |
+----------+        TCP/JSON               |
| Client B | -----------------------------+
+----------+

Destination Server -> Proxy Server -> Client corect
```

Componente:

* `client/demo_client.py` – client demo pentru rularea scenariilor
* `proxy/proxy_server.py` – serverul proxy
* `destination/destination_server.py` – serverul destinatie
* `docker-compose.yml` – porneste serviciile `proxy` si `destination`

## 4. Porturi folosite

| Componenta         |   Port |
| ------------------ | -----: |
| Proxy Server       | `9000` |
| Destination Server | `9101` |

In Docker Compose, proxy-ul contacteaza serverul destinatie folosind numele serviciului:

```text
destination:9101
```

Nu foloseste `127.0.0.1:9101` in interiorul containerului, deoarece `127.0.0.1` ar indica spre containerul proxy, nu spre containerul destination.

## 5. Rulare proiect

### 5.1 Pornire servere

Din radacina proiectului:

```bash
docker compose up --build
```

Aceasta comanda porneste:

* containerul `rechini-proxy`
* containerul `rechini-destination`

Proxy-ul va asculta pe portul `9000`, iar destination server pe portul `9101`.

### 5.2 Rulare client demo

Intr-un terminal separat:

```bash
python3 client/demo_client.py full
```

Sau:

```bash
source .venv/bin/activate
python3 client/demo_client.py full
```

### 5.3 Oprire proiect

```bash
docker compose down
```

## 6. Scenarii demo

Clientul demo suporta mai multe scenarii.

### Demo complet

```bash
python3 client/demo_client.py full
```

Acest scenariu ruleaza:

1. `proxy_ping`
2. `echo` prin destination server
3. `uppercase` prin destination server
4. `delay_echo` cu raspunsuri out-of-order
5. `proxy_read_file`
6. target invalid

### Cerere directa catre proxy

```bash
python3 client/demo_client.py ping
```

Trimite o cerere `proxy_ping` catre proxy si verifica daca acesta raspunde.

### Cereri catre destination server

```bash
python3 client/demo_client.py destination
```

Trimite cereri `echo` si `uppercase` prin proxy catre destination server.

### Raspunsuri out-of-order

```bash
python3 client/demo_client.py out-of-order
```

Clientul A trimite primul o cerere lenta:

```text
delay_ms = 3000
```

Clientul B trimite al doilea o cerere rapida:

```text
delay_ms = 500
```

Rezultatul corect este ca raspunsul Clientului B apare primul, desi cererea lui a fost trimisa dupa cererea Clientului A. Proxy-ul livreaza raspunsurile corect folosind `request_id`.

### Citire fisier din proxy

```bash
python3 client/demo_client.py read-file
```

Trimite o cerere `proxy_read_file` catre proxy. Proxy-ul citeste fisierul `sample.txt` din directorul expus si returneaza continutul.

### Target invalid

```bash
python3 client/demo_client.py invalid-target
```

Trimite o cerere cu target invalid. Proxy-ul trebuie sa raspunda controlat cu eroare.

### Destination server indisponibil

In terminalul in care ruleaza Docker Compose, lasati proxy-ul pornit si opriti doar destination server:

```bash
docker compose stop destination
```

Apoi rulati:

```bash
python3 client/demo_client.py unavailable
```

Raspunsul asteptat este o eroare controlata:

```json
{
  "status": "error",
  "error": {
    "code": "DESTINATION_UNAVAILABLE",
    "message": "Server destination unavailable"
  }
}
```

Dupa test, reporniti destination server:

```bash
docker compose start destination
```

## 7. Protocolul aplicatiei

Aplicatia foloseste un protocol text peste TCP.

Fiecare mesaj este:

* un obiect JSON
* scris pe o singura linie
* terminat cu newline (`\n`)

Acest format permite citirea mesajelor cu `readline()`.

### 7.1 Client -> Proxy

```json
{"type":"REQUEST","target":"destination","operation":"delay_echo","payload":{"text":"salut","delay_ms":2000}}
```

Campuri:

| Camp        | Descriere                                     |
| ----------- | --------------------------------------------- |
| `type`      | tipul mesajului; pentru client este `REQUEST` |
| `target`    | `proxy` sau `destination`                     |
| `operation` | operatia ceruta                               |
| `payload`   | datele necesare operatiei                     |

### 7.2 Proxy -> Destination

```json
{"type":"FORWARDED_REQUEST","request_id":"uuid","operation":"delay_echo","payload":{"text":"salut","delay_ms":2000}}
```

Proxy-ul adauga campul `request_id`.

### 7.3 Destination -> Proxy

```json
{"type":"DESTINATION_RESPONSE","request_id":"uuid","status":"ok","data":{"text":"salut","delay_ms":2000}}
```

Destination server raspunde cu acelasi `request_id`.

### 7.4 Proxy -> Client

```json
{"type":"RESPONSE","request_id":"uuid","status":"ok","data":{"text":"salut","delay_ms":2000}}
```

Proxy-ul foloseste `request_id` pentru a trimite raspunsul catre clientul corect.

### 7.5 Raspuns de eroare

```json
{"type":"RESPONSE","request_id":"uuid","status":"error","error":{"code":"DESTINATION_UNAVAILABLE","message":"Server destination unavailable"}}
```

## 8. Operatii suportate

### 8.1 Operatii executate direct de proxy

| Operatie          | Descriere                                            |
| ----------------- | ---------------------------------------------------- |
| `proxy_ping`      | verifica daca proxy-ul raspunde                      |
| `proxy_read_file` | citeste un fisier din directorul expus al proxy-ului |

Exemplu `proxy_ping`:

```json
{"type":"REQUEST","target":"proxy","operation":"proxy_ping","payload":{}}
```

Exemplu `proxy_read_file`:

```json
{"type":"REQUEST","target":"proxy","operation":"proxy_read_file","payload":{"filename":"sample.txt"}}
```

### 8.2 Operatii trimise catre destination server

| Operatie     | Descriere                                   |
| ------------ | ------------------------------------------- |
| `echo`       | returneaza textul primit                    |
| `uppercase`  | returneaza textul cu litere mari            |
| `delay_echo` | asteapta `delay_ms`, apoi returneaza textul |

Exemplu `echo`:

```json
{"type":"REQUEST","target":"destination","operation":"echo","payload":{"text":"salut"}}
```

Exemplu `uppercase`:

```json
{"type":"REQUEST","target":"destination","operation":"uppercase","payload":{"text":"salut"}}
```

Exemplu `delay_echo`:

```json
{"type":"REQUEST","target":"destination","operation":"delay_echo","payload":{"text":"salut","delay_ms":1000}}
```

## 9. Coduri de eroare

| Cod                       | Cand apare                                             |
| ------------------------- | ------------------------------------------------------ |
| `INVALID_REQUEST`         | mesaj JSON invalid, campuri lipsa sau target invalid   |
| `UNKNOWN_OPERATION`       | operatia nu este suportata                             |
| `DESTINATION_UNAVAILABLE` | serverul destinatie nu poate fi contactat              |
| `INVALID_RESPONSE_ID`     | destination server raspunde fara un `request_id` valid |
| `CLIENT_DISCONNECTED`     | clientul s-a deconectat inainte de raspuns             |

## 10. Cum functioneaza request_id

Pentru fiecare cerere valida, proxy-ul genereaza un identificator unic (`request_id`).

Proxy-ul memoreaza intern asocierea:

```text
request_id -> client
```

Aceasta mapare este necesara pentru ca mai multi clienti pot trimite cereri simultan, iar raspunsurile de la destination server pot veni in alta ordine decat cererile.

Exemplu:

```text
Client A trimite delay_echo cu 3000 ms
Client B trimite delay_echo cu 500 ms

Destination raspunde mai intai pentru Client B.
Proxy-ul foloseste request_id-ul ca sa trimita raspunsul catre Client B.
Apoi trimite raspunsul lent catre Client A.
```

Astfel, raspunsurile sunt corelate corect chiar si in scenarii out-of-order.

## 11. Concurenta

Proxy-ul si destination server-ul folosesc `asyncio`.

Proxy-ul poate accepta mai multi clienti si poate procesa mai multe cereri in paralel. Cand o cerere asteapta raspuns de la destination server, event loop-ul poate continua sa proceseze alte conexiuni.

Acest comportament permite scenariul cu raspunsuri out-of-order.

## 12. Inspectare trafic cu Wireshark

Pentru observarea traficului, se poate folosi Wireshark.

Filtru recomandat:

```text
tcp.port == 9000 || tcp.port == 9101
```

Portul `9000` este folosit pentru comunicarea client -> proxy.

Portul `9101` este folosit pentru comunicarea proxy -> destination server.

In payload-ul TCP se pot observa mesajele JSON trimise intre componente.

## 13. Structura proiectului

```text
.
├── client/
│   └── demo_client.py
├── destination/
│   ├── destination_server.py
│   └── Dockerfile
├── proxy/
│   ├── proxy_server.py
│   └── Dockerfile
├── docs/
│   └── ...
├── docker-compose.yml
└── README.md
```

## 14. Contributii

| Membru                 | Responsabilitate principala  |
| ---------------------- | ---------------------------- |
| Mincinoiu Dragos-Matei | Proxy server                 |
| Ionescu Sabina         | Destination server si Docker |
| Mihailescu Valter-Ioan | Client demo si documentatie  |

## 15. Verificari utile pentru dezvoltare

Verificare sintaxa Python:

```bash
python3 -m py_compile proxy/proxy_server.py destination/destination_server.py client/demo_client.py
```

Verificare Ruff:

```bash
ruff check proxy/proxy_server.py destination/destination_server.py client/demo_client.py
```

Verificare Docker Compose:

```bash
docker compose config
```

Build si rulare:

```bash
docker compose up --build
```

## 16. Probleme posibile

### Port deja ocupat

Daca portul `9000` sau `9101` este deja folosit, opriti procesul care foloseste portul sau modificati porturile in `docker-compose.yml`.

### Destination indisponibil

Daca proxy-ul nu poate contacta destination server, clientul primeste eroarea:

```text
DESTINATION_UNAVAILABLE
```

### Diferenta dintre localhost si Docker

Local, `127.0.0.1` inseamna calculatorul curent.

In interiorul unui container Docker, `127.0.0.1` inseamna containerul curent. De aceea, proxy-ul foloseste `destination` ca host pentru a contacta containerul destination in reteaua Docker Compose.
