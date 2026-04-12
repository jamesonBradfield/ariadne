class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b

    def multiply(self, a, b):
        return a * b

    def divide(self, a, b):
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b


class TestCalculator:
    def test_add(self):
        calc = Calculator()
        assert calc.add(2, 3) == 5
        assert calc.add(-1, 1) == 0

    def test_subtract(self):
        calc = Calculator()
        assert calc.subtract(5, 3) == 2
        assert calc.subtract(0, 5) == -5

    def test_multiply(self):
        calc = Calculator()
        assert calc.multiply(2, 3) == 6
        assert calc.multiply(0, 100) == 0

    def test_divide(self):
        calc = Calculator()
        assert calc.divide(6, 2) == 3
        assert calc.divide(5, 2) == 2.5

    def test_divide_by_zero(self):
        calc = Calculator()
        try:
            calc.divide(5, 0)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
