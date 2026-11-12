"""
Base interface for AI CLI adapters with dynamic model and reasoning effort support.

İstem komut satırı argümanı olarak GEÇMEZ (`.cmd` kabuğu çok satırlı metni bozar, LLM çıktısındaki
`"` ve `&` cmd.exe üzerinden komut enjeksiyonuna açar): her adaptör `prepare()` ile istemi stdin'e ya da
geçici dosyaya koyar. `build_command` yalnız istemi argümanla verebilen gerçek exe'ler (agy) için kalır.
"""
import asyncio
import codecs
import os
import shutil
import subprocess
import sys
import time
from typing import Callable, List, Optional, Tuple

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
DEFAULT_TIMEOUT_SEC = 1800


def kill_process_tree(pid: Optional[int]) -> None:
    """Süreci ve altındakileri öldürür (.cmd kabuğunun altındaki node/exe de ölsün)."""
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=30,
            )
        else:
            os.kill(pid, 9)
    except Exception:
        pass


class BaseCLIAdapter:
    def __init__(self, key: str, name: str, binary: str, default_model: str, default_effort: str = "high"):
        self.key = key
        self.name = name
        self.binary = binary
        self.default_model = default_model
        self.default_effort = default_effort
        self.resolved_binary = shutil.which(binary) or binary
        self.is_running = False
        self._current_process: Optional[asyncio.subprocess.Process] = None

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        """Subclasses construct their specific CLI argument list with model and effort."""
        raise NotImplementedError

    def prepare(
        self,
        prompt: str,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Tuple[List[str], Optional[bytes], List[str]]:
        """Çalıştırma hazırlığı: (komut, stdin baytları ya da None, işten sonra silinecek geçici dosyalar).

        Varsayılan: istem argümanda (yalnız gerçek exe'ler için güvenli), stdin yok.
        """
        return self.build_command(prompt, model=model, effort=effort), None, []

    async def execute(
        self,
        prompt: str,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        cwd: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT_SEC,
    ) -> Tuple[int, str, float]:
        """
        Runs the CLI command asynchronously, streaming output line-by-line via `on_output`.
        Returns: (exit_code, full_output, duration_seconds)
        """
        work_dir = cwd or os.getcwd()
        start_time = time.time()
        self.is_running = True
        output_chunks: List[str] = []   # stdout: sonuç metni
        err_chunks: List[str] = []      # stderr: canlı çıktıda görünür; hata durumunda sonuca eklenir
        temp_files: List[str] = []
        feeder: Optional[asyncio.Task] = None

        try:
            cmd, stdin_bytes, temp_files = self.prepare(prompt, model=model, effort=effort, cwd=work_dir)

            if on_output:
                on_output(f"[dim grey]>>> Başlatılıyor: {' '.join(cmd[:4])} ...[/dim grey]\n")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                # Ayrı boru: CLI'ların stderr uyarıları (ör. claude'un settings.json izin uyarısı) canlı
                # çıktıda görünür ama sonuç metnine karışmaz; şef onları "işçi raporu" sanıp yorumlamasın.
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                creationflags=CREATE_NO_WINDOW,
            )
            self._current_process = process

            async def feed_stdin():
                # Büyük istem boru tamponunu aşabilir: yazma, çıktı okumasından ayrı bir görevde.
                try:
                    process.stdin.write(stdin_bytes)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass

            if stdin_bytes is not None:
                feeder = asyncio.create_task(feed_stdin())

            async def read_stream(stream, hedef: List[str]):
                # readline() 64 KB'tan uzun tek satırda patlar (uzun JSON/satır basan CLI): parça parça
                # oku, satırlara kendimiz böl. Çok uzun satır 64 KB'ta parça parça iletilir.
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                bekleyen = ""

                def ilet(metin: str):
                    hedef.append(metin)
                    if on_output:
                        on_output(metin)

                while True:
                    parca = await stream.read(16384)
                    if not parca:
                        break
                    bekleyen += decoder.decode(parca)
                    while "\n" in bekleyen:
                        satir, bekleyen = bekleyen.split("\n", 1)
                        ilet(satir + "\n")
                    if len(bekleyen) > 65536:
                        ilet(bekleyen)
                        bekleyen = ""
                bekleyen += decoder.decode(b"", final=True)
                if bekleyen:
                    ilet(bekleyen)

            async def read_all():
                await asyncio.gather(read_stream(process.stdout, output_chunks), read_stream(process.stderr, err_chunks))
                await process.wait()

            try:
                await asyncio.wait_for(read_all(), timeout=timeout)
            except asyncio.TimeoutError:
                kill_process_tree(process.pid)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except Exception:
                    pass
                err_msg = f"Zaman aşımı: {self.name} {int(timeout or 0)} saniyede bitmedi, süreç öldürüldü.\n"
                if on_output:
                    on_output(f"[bold red]{err_msg}[/bold red]")
                partial = "".join(output_chunks) + "".join(err_chunks)
                return (-1, partial + err_msg, time.time() - start_time)

            exit_code = process.returncode or 0
        except FileNotFoundError:
            err_msg = f"[bold red]Hata: '{self.binary}' bulunamadı. Lütfen PATH ayarlarını kontrol edin.[/bold red]\n"
            if on_output:
                on_output(err_msg)
            return (-1, err_msg, time.time() - start_time)
        except asyncio.CancelledError:
            if self._current_process and self._current_process.returncode is None:
                kill_process_tree(self._current_process.pid)
            raise
        except Exception as e:
            err_msg = f"[bold red]Çalıştırma hatası: {e}[/bold red]\n"
            if on_output:
                on_output(err_msg)
            return (-1, err_msg, time.time() - start_time)
        finally:
            if feeder is not None and not feeder.done():
                feeder.cancel()
            for path in temp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass
            self.is_running = False
            self._current_process = None

        duration = time.time() - start_time
        full_text = "".join(output_chunks)
        # Çıktı boşsa ya da süreç hatayla bittiyse nedeni stderr'de olur: sonuca eklenir ki şef/kullanıcı görsün.
        if exit_code != 0 or not full_text.strip():
            full_text += "".join(err_chunks)
        return (exit_code, full_text, duration)

    async def cancel(self):
        """Terminates the running process (and its children) if active."""
        proc = self._current_process
        if proc and self.is_running:
            try:
                if proc.returncode is None:
                    kill_process_tree(proc.pid)
                    await asyncio.sleep(0.2)
                    if proc.returncode is None:
                        proc.kill()
            except Exception:
                pass
            self.is_running = False
