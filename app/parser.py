"""
@File: parser.py
@Author: Dominik Vondruška
@Project: Bakalářská práce — Systém pro monitorování otevřených dat v reálném čase
"""
import xml.etree.ElementTree as ET

def parse_datex_xml(xml_data: str) -> dict:
    """
    Pokusí se zpracovat XML data ve formě řetězce a převést je na strukturu ElementTree.
    Vrací slovník s informací o úspěchu parsování a názvu kořenového tagu.
    V případě chyby vrací slovník s popisem chyby.
    """
    try:
        root = ET.fromstring(xml_data)
        return {"status": "parsed", "tag": root.tag}
    except Exception as e:
        return {"error": str(e)}