import re
# noinspection PyProtectedMember
from asyncio.subprocess import PIPE, create_subprocess_exec


class TLSCipherSuiteChecker:

    def __init__(self, host):
        self.target = host.target

    async def scan_ciphers(self, port):
        script = "nmap --script ssl-enum-ciphers -p {} {}".format(str(port), self.target).split()
        process = await create_subprocess_exec(
            *script,
            stdout=PIPE,
            stderr=PIPE
        )
        result, err = await process.communicate()
        if process.returncode != 0:
            parsed = err.decode().strip()
        else:
            parsed = self._parse_nmap_outpt(result)
        return parsed

    @staticmethod
    def _parse_nmap_outpt(result):
        result = result.decode().strip().split('\n')
        return '\n'.join([line for line in result if "TLS" in line or "ciphers" in line]).strip().rstrip()


# noinspection PyTypeChecker
class TLSInfoScanner(TLSCipherSuiteChecker):

    def __init__(self, host, port=443):
        super().__init__(host)
        self.target = host.target
        self.port = port
        self._versions = ("tls1", "tls1_1", "tls1_2")
        # OpenSSL likes to hang, Linux timeout to the rescue
        self._base_script = "timeout 10 openssl s_client -connect {}:443 ".format(self.target)
        self.begin = "-----BEGIN CERTIFICATE-----"
        self.end = "-----END CERTIFICATE-----"
        self.sni_data = {}
        self.non_sni_data = {}
        self.ciphers = ""

    async def run(self, sni=True):
        path = "{}/tls_data.txt".format(self.target)
        print("Started collecting TLS data.\n"
              "Will write results to {}".format(path))
        # self.ciphers = await self.scan_ciphers(self.port)
        self.non_sni_data = await self._extract_ssl_data()
        if sni:
            self.sni_data = await self._extract_ssl_data(sni=sni)
        await self.heartbleed_vulnerable()
        print("Done collecting TLS data")
        # self.write_up(path)
        print(self.sni_data)
        print(type(self.sni_data))
        print(self.non_sni_data)
        print(type(self.non_sni_data))
    def is_certificate(self, text):
        if self.begin in text and self.end in text:
            return True
        return

    def get_certificate(self, text):
        ######
        pass

    async def heartbleed_vulnerable(self):
        script = self._base_script + "-tlsextdebug"
        process = await create_subprocess_exec(
            *script.split(),
            stdout=PIPE,
            stderr=PIPE
        )
        result, err = await process.communicate()
        try:
            if "server extension \"heartbeat\" (id=15)" in result.decode().strip():
                print("Target seems to be vulnerable to Heartbleed - CVE-2014-0160")
        except TypeError:  # Type error means no result
            pass

    async def _extract_ssl_data(self, sni=False):
        """Test for version support (SNI/non-SNI), get all SANs, get certificate"""
        # Do for all responses
        responses = await self._exec_openssl(self._base_script, sni)
        tls_dict = self._parse_sclient_output(responses)
        # Do for one successful SSL response
        for res in responses:
            if self.is_certificate(res):
                tls_dict["SANs"] = await self._parse_san_output(res)
                break
        return tls_dict

    async def _exec_openssl(self, script, sni=False):
        processes = []
        outputs = []
        if sni:
            script += " -servername {}".format(self.target)
        for v in self._versions:
            curr = (script + ' -{}'.format(v)).split()
            processes.append(
                await create_subprocess_exec(
                    *curr,
                    stdout=PIPE,
                    stderr=PIPE
                )
            )
        for p in processes:
            result, err = await p.communicate()

            outputs.append(result.decode().strip())
        return outputs

    @staticmethod
    async def _parse_san_output(data):
        process = await create_subprocess_exec(
            "openssl", "x509", "-noout", "-text",
            stdin=PIPE,
            stderr=PIPE,
            stdout=PIPE
        )
        result, err = await process.communicate(input=bytes(data, encoding='ascii'))
        sans = re.findall(r"DNS:\S*\b", result.decode().strip())
        return {san.replace("DNS:", '') for san in sans}

    def _parse_sclient_output(self, results):
        is_supported = {"TLSv1": False, "TLSv1.1": False, "TLSv1.2": False}
        for res in results:
            if not self.is_certificate(res):
                continue
            for line in res.split('\n'):
                if "Protocol" in line:
                    ver = line.strip().split(':')[1].strip()
                    is_supported[ver] = True
        return is_supported

    def write_up(self, path):
        with open(path, "w") as file:
            file.write("Supporting Ciphers:\n")
            file.write(self.ciphers+"\n")
            file.write("SNI Data:\n")
            for k, v in self.sni_data.items():
                file.write("{}: {}\n".format(k, v))
            file.write("non-SNI Data:\n")
            for k, v in self.sni_data.items():
                file.write("{}: {}\n".format(k, v))
