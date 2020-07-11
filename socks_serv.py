import asyncio
import argparse
import struct
import socket
import logging
logging.basicConfig(filename=None, format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)
logging.basicConfig()

SOCKS_VERSION = 5

def parse_command_line(description):
    """Parse command line and return a socket address."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('host', help='IP or hostname')
    parser.add_argument('-p', metavar='port', type=int, default=1060,
        help='TCP port (default 1060)')
    args = parser.parse_args()
    address = (args.host, args.p)
    return address


async def get_available_methods(n, reader):
    methods = []
    for i in range(n):
        methods.append(ord(await reader.read(1)))
    return methods

async def write_to(reader, writer):
    while True:
        buf = await reader.read(4096)
        if not buf:
            writer.close()
            break
        writer.write(buf)
        await writer.drain()

async def handle_connection(reader, writer):
    def generate_failed_reply(address_type, error_number):
        return struct.pack("!BBBBIH", SOCKS_VERSION, error_number, 0, address_type, 0, 0)

    address = writer.get_extra_info('peername')
    logging.info('Accepted connection from {}'.format(address))
    header = await reader.read(2)
    version, nmethods = struct.unpack("!BB", header)
    
    if version != SOCKS_VERSION or nmethods <= 0:
        writer.close()

    methods = await get_available_methods(nmethods, reader)

    if 0 not in set(methods):
        writer.close()

    writer.write(struct.pack("!BB", SOCKS_VERSION, 0))

    version, cmd, _, address_type = struct.unpack("!BBBB", await reader.read(4))
    if version != SOCKS_VERSION:
        writer.close()
    if address_type == 1:
        addr = socket.inet_ntop(socket.AF_INET, await reader.read(4))
    elif address_type == 3:
        domain_length = (await reader.read(1))[0]
        addr = await reader.read(domain_length)
        addr = socket.gethostbyname(addr.decode("UTF-8"))
    elif address_type == 4:
        addr = socket.inet_ntop(socket.AF_INET6, await reader.read(16))
    else:
        writer.close()
    port = struct.unpack('!H', await reader.read(2))[0]

    try:
        if cmd == 1:
            remote_reader, remote_writer = await asyncio.open_connection(addr, port)
        else:
            writer.close()
        reply = struct.pack("!BBBBIH", SOCKS_VERSION, 0, 0, 1, struct.unpack("!I", socket.inet_aton(addr))[0], port)
    except Exception as err:
        logging.error(err)
        reply = generate_failed_reply(address_type, t)
    writer.write(reply)
    if reply[1] == 0 and cmd == 1:
        remote_reader, remote_writer = await asyncio.open_connection(addr, port)
        logging.info("Connected to {}:{}".format(addr, port))
        remote_to_local_t = asyncio.create_task(write_to(remote_reader, writer))
        local_to_remote_t = asyncio.create_task(write_to(reader, remote_writer))
        await asyncio.gather(
            remote_to_local_t,
            local_to_remote_t
        )
                

async def main(address):
    server = await asyncio.start_server(
            handle_connection, *address)
    addr = server.sockets[0].getsockname()
    logging.info('Listening at {}'.format(addr))
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    address = parse_command_line('simple socks server')
    asyncio.run(main(address))
