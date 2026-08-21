import os
import requests
import json
import sys
import time
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from credenciais import (  # noqa: E402
    BASE_URL,
    selecionar as selecionar_organizacao,
)

# NOTA: as orgs antes chamadas aqui de "poc1" e "poc2" agora seguem o nome
# canônico de credenciais.py — "poc" e "pocs". O comando muda junto.

# Headers para baixar imagens do Mercado Livre (sem User-Agent o ML bloqueia)
IMG_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.mercadolivre.com.br/",
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
}

# Se True, converte qualquer imagem (webp/png/etc) para JPEG antes do upload.
CONVERTER_PARA_JPEG = True


def request_with_retry(method, url, **kwargs):
    """Executa requisições tratando o erro 429 (Rate Limit)."""
    wait_time = 15
    response = None
    for _ in range(5):
        response = requests.request(method, url, **kwargs)
        if response.status_code == 429:
            print(f"[AVISO] Limite atingido. Aguardando {wait_time}s...")
            time.sleep(wait_time)
            wait_time *= 2
            continue
        return response
    return response


def baixar_imagem(image_url):
    """Baixa imagem com User-Agent e valida o conteúdo. Retorna (bytes, mime, fname)."""
    resp = requests.get(image_url, headers=IMG_DOWNLOAD_HEADERS, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"download status={resp.status_code}")
    if len(resp.content) < 1000:
        raise RuntimeError(f"download retornou {len(resp.content)} bytes (provável bloqueio)")

    content = resp.content

    url_clean = image_url.lower().split("?")[0]
    if url_clean.endswith(".webp"):
        fname, mime = "image.webp", "image/webp"
    elif url_clean.endswith(".png"):
        fname, mime = "image.png", "image/png"
    elif url_clean.endswith(".gif"):
        fname, mime = "image.gif", "image/gif"
    else:
        fname, mime = "image.jpg", "image/jpeg"

    if CONVERTER_PARA_JPEG and mime != "image/jpeg":
        try:
            from PIL import Image
            img = Image.open(BytesIO(content)).convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            content = buf.getvalue()
            fname, mime = "image.jpg", "image/jpeg"
        except ImportError:
            print("  [AVISO] Pillow não instalado — enviando webp original. "
                  "Instale com: pip install Pillow")
        except Exception as e:
            print(f"  [AVISO] Falha ao converter para JPEG ({e}) — enviando original.")

    return content, mime, fname


def update_product_images(json_file, headers):
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            products_to_update = json.load(f)
    except Exception as e:
        print(f"[ERRO] Falha ao ler arquivo: {e}")
        return

    print(f"Iniciando atualização de {len(products_to_update)} produtos.\n")

    for item in products_to_update:
        product_id = item.get("product_id")
        image_url = item.get("image_url")

        try:
            res_get = request_with_retry("GET", f"{BASE_URL}/products/{product_id}", headers=headers)
            if res_get.status_code != 200:
                print(f"[ERRO] Produto {product_id} não encontrado.")
                continue

            product_data = res_get.json()
            display_name = product_data.get("name") or product_id
            print(f"Processando: {display_name}")

            try:
                img_content, mime, fname = baixar_imagem(image_url)
                print(f"  → imagem baixada: {len(img_content)} bytes, MIME={mime}")
            except Exception as e:
                print(f"  [FALHA] Download da imagem: {e}")
                continue

            files = {'files': (fname, img_content, mime)}
            upload_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
            res_file = request_with_retry("POST", f"{BASE_URL}/resource-files",
                                          headers=upload_headers, files=files)

            if res_file.status_code in (200, 201):
                file_id = res_file.json()['resourceFiles'][0]['id']

                product_data['images'] = [{"resource_file_id": file_id, "main": True}]

                for key in ['id', 'created_at', 'updated_at', 'brand', 'category']:
                    product_data.pop(key, None)

                headers_json = {**headers, "Content-Type": "application/json"}
                res_put = request_with_retry("PUT", f"{BASE_URL}/products/{product_id}",
                                             headers=headers_json, json=product_data)

                if res_put.status_code in (200, 204):
                    print(f"[OK] {display_name} atualizado com sucesso.")
                else:
                    print(f"[FALHA] Erro ao salvar {display_name}: {res_put.text[:200]}")
            else:
                print(f"[FALHA] Erro no upload da imagem para {display_name}. "
                      f"status={res_file.status_code} body={res_file.text[:200]}")

        except Exception as e:
            print(f"[ERRO] Falha no ID {product_id}: {e}")

        time.sleep(5)


if __name__ == "__main__":
    # Uso: python atualizar_imagens.py [arquivo.json] [organizacao]
    # Exemplos:
    #   python atualizar_imagens.py produtos.json poc
    #   python atualizar_imagens.py produtos.json sankhya
    #   python atualizar_imagens.py produtos.json    ← pergunta interativamente
    #   python atualizar_imagens.py                  ← usa arquivo padrão e pergunta org

    # O padrão sai da pasta deste arquivo — o caminho absoluto que estava aqui
    # apontava para "Automação POCs/Arquivos Json", que não existe: a pasta é
    # "Automação POCs/poc-portais/Arquivos Json".
    padrao = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "Arquivos Json", "produtos_pendentes.json")
    arquivo = sys.argv[1] if len(sys.argv) > 1 else padrao
    org_chave = sys.argv[2] if len(sys.argv) > 2 else None

    headers, _ = selecionar_organizacao(org_chave)
    update_product_images(arquivo, headers)