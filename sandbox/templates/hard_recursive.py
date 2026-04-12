def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
