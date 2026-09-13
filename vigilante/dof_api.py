"""Cliente de la API pública del SIDOF (Diario Oficial de la Federación).

Capa determinista: sin caché y sin LLM. Cada corrida golpea la API en vivo,
que es lo correcto cuando esto vive detrás de un cron job (la edición
vespertina y las extraordinarias aparecen más tarde en el día).

Endpoints verificados:
    GET /dof/sidof/notas/{DD-MM-YYYY}   -> notas del día (título, dependencia, codNota)
    GET /dof/sidof/notas/nota/{codNota} -> nota completa, HTML en `cadenaContenido`
    GET /dof/sidof/diarios/porFecha/{DD-MM-YYYY} -> ediciones publicadas ese día
    GET /dof/sidof/buscarNotas/titulo/{frase}/{pagina}/{limite}/fecha/desc -> histórico
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

import httpx

BASE_URL = "https://sidof.segob.gob.mx/dof/sidof"
URL_PUBLICA = "https://sidof.segob.gob.mx/notas/{cod_nota}"
TIMEOUT = 30.0


@dataclass
class Nota:
    """Una entrada del sumario del día. No incluye el texto completo."""

    cod_nota: int
    titulo: str
    dependencia: str
    poder: str
    edicion: str  # MAT | VES | EXT
    seccion: str
    fecha: str  # DD-MM-YYYY
    pagina: int = 0

    @property
    def url(self) -> str:
        return URL_PUBLICA.format(cod_nota=self.cod_nota)

    def to_dict(self) -> dict:
        return {
            "cod_nota": self.cod_nota,
            "titulo": self.titulo,
            "dependencia": self.dependencia,
            "poder": self.poder,
            "edicion": self.edicion,
            "seccion": self.seccion,
            "fecha": self.fecha,
            "url": self.url,
        }


@dataclass
class DiarioDelDia:
    fecha: str
    notas: list[Nota] = field(default_factory=list)

    @property
    def hubo_publicacion(self) -> bool:
        return bool(self.notas)


@dataclass
class Coincidencia:
    """Una fila del histórico. La búsqueda no devuelve edición ni sección."""

    cod_nota: int
    titulo: str
    fecha: str  # DD-MM-YYYY
    dependencia: str

    @property
    def url(self) -> str:
        return URL_PUBLICA.format(cod_nota=self.cod_nota)

    def to_dict(self) -> dict:
        return {
            "cod_nota": self.cod_nota,
            "titulo": self.titulo,
            "fecha": self.fecha,
            "dependencia": self.dependencia,
            "url": self.url,
        }


@dataclass
class ResultadoBusqueda:
    frase: str
    total: int  # cuántas hay en todo el DOF, no cuántas devolvimos
    coincidencias: list[Coincidencia] = field(default_factory=list)


class _Destildador(HTMLParser):
    """Extrae texto legible de las notas del DOF, que vienen como HTML 4.01 crudo."""

    _IGNORAR = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._partes: list[str] = []
        self._saltar = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORAR:
            self._saltar += 1
        elif tag in ("p", "br", "div", "tr", "table"):
            self._partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self._IGNORAR and self._saltar:
            self._saltar -= 1

    def handle_data(self, data):
        if not self._saltar:
            self._partes.append(data)

    def texto(self) -> str:
        crudo = "".join(self._partes)
        crudo = crudo.replace("\xa0", " ")
        crudo = re.sub(r"[ \t]+", " ", crudo)
        crudo = re.sub(r"\n\s*\n+", "\n\n", crudo)
        return crudo.strip()


def html_a_texto(html: str) -> str:
    parser = _Destildador()
    parser.feed(html or "")
    return parser.texto()


def _get(cliente: httpx.Client, ruta: str) -> dict:
    respuesta = cliente.get(f"{BASE_URL}{ruta}")
    respuesta.raise_for_status()
    datos = respuesta.json()
    if datos.get("messageCode") != 200:
        raise RuntimeError(f"El DOF respondió {datos.get('messageCode')}: {datos.get('response')}")
    return datos


def notas_del_dia(fecha: str) -> DiarioDelDia:
    """Sumario completo de una fecha DD-MM-YYYY.

    Las filas sin `titulo` son encabezados de dependencia del sumario impreso,
    no publicaciones; se descartan aquí para que nadie más tenga que saberlo.
    """
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as cliente:
        datos = _get(cliente, f"/notas/{fecha}")

    notas: list[Nota] = []
    for clave, edicion in (
        ("NotasMatutinas", "MAT"),
        ("NotasVespertinas", "VES"),
        ("NotasExtraordinarias", "EXT"),
    ):
        for cruda in datos.get(clave) or []:
            titulo = (cruda.get("titulo") or "").strip()
            if not titulo:
                continue
            notas.append(
                Nota(
                    cod_nota=cruda["codNota"],
                    titulo=titulo,
                    dependencia=(cruda.get("codOrgaDos") or "SIN DEPENDENCIA").strip(),
                    poder=(cruda.get("codOrgaUno") or "").strip(),
                    edicion=edicion,
                    seccion=(cruda.get("codSeccion") or "").strip(),
                    fecha=cruda.get("fecha") or fecha,
                    pagina=cruda.get("pagina") or 0,
                )
            )

    notas.sort(key=lambda n: n.cod_nota)
    return DiarioDelDia(fecha=fecha, notas=notas)


def buscar_por_titulo(frase: str, limite: int = 20, pagina: int = 1) -> ResultadoBusqueda:
    """Histórico del DOF por frase contenida en el título, más reciente primero.

    El endpoint hace match de substring y el guion parte la frase en OR, así que
    esto solo discrimina con frases de materia de 2-4 palabras (R14): `NOM-253`
    devuelve 144,835 filas y `sangre humana` devuelve 17. Quien llame se encarga
    de elegir la frase; aquí no se adivina.
    """
    frase = (frase or "").strip()
    if not frase:
        raise ValueError("La frase de búsqueda no puede ir vacía")

    ruta = f"/buscarNotas/titulo/{urllib.parse.quote(frase, safe='')}/{pagina}/{limite}/fecha/desc"
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as cliente:
        datos = _get(cliente, ruta)

    coincidencias = [
        Coincidencia(
            cod_nota=fila["codNota"],
            titulo=(fila.get("titulo") or "").strip(),
            fecha=(fila.get("fecha") or "").strip(),
            dependencia=(fila.get("codOrgaDos") or "SIN DEPENDENCIA").strip(),
        )
        for fila in datos.get("Notas") or []
        if fila.get("codNota") and (fila.get("titulo") or "").strip()
    ]
    return ResultadoBusqueda(
        frase=frase,
        total=int(datos.get("totalRegistros") or len(coincidencias)),
        coincidencias=coincidencias,
    )


@dataclass
class TextoNota:
    """Resultado de leer una nota completa, con diagnóstico de disponibilidad.

    `disponible=False` no es un error: la publicación existe en el DOF (tiene
    `codNota`, título y fecha) pero no tiene texto extraíble por esta vía. Caso
    real confirmado: `codNota 4432291` (DECRETO Ley Electoral, 06-02-1917) trae
    `cadenaContenido` vacío y los tres flags `existe*` en `"N"` — ni HTML, ni
    imagen, ni PDF. Sin este flag, quien llama no puede distinguir eso de "esta
    nota de verdad no dice nada".
    """

    texto: str
    disponible: bool
    existe_doc: bool
    existe_imagen: bool
    existe_pdf: bool


def texto_nota(cod_nota: int) -> TextoNota:
    """Texto completo de una nota, ya convertido de HTML a texto plano.

    `disponible` es `False` únicamente cuando el texto extraído queda
    exactamente vacío — no hay umbral de "insuficiente": el DOF publica
    decretos legítimos de una sola frase, y un umbral por encima de cero
    marcaría eso como "no disponible" sin motivo.
    """
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as cliente:
        datos = _get(cliente, f"/notas/nota/{cod_nota}")

    nota = datos.get("Nota")
    if not nota:
        raise LookupError(f"La nota {cod_nota} no existe en el DOF")

    texto = html_a_texto(nota.get("cadenaContenido") or "")
    return TextoNota(
        texto=texto,
        disponible=bool(texto.strip()),
        existe_doc=nota.get("existeDoc") == "S",
        existe_imagen=nota.get("existeImagen") == "S",
        existe_pdf=nota.get("existePdf") == "S",
    )
