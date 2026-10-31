from concurrent.futures import ThreadPoolExecutor

from emporio.text import analyze


def test_analyze_is_safe_across_threads():
    text = "Violões elétricos, instrumentos musicais e promoções disponíveis " * 50
    expected = analyze(text)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(analyze, [text] * 200))
    assert all(result == expected for result in results)
