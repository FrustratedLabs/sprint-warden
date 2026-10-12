package shapes

import (
	"math"
	"testing"
)

func Test_S01_RectangleArea(t *testing.T) {
	if got := RectangleArea(3, 4); got != 12 {
		t.Fatalf("expected 12 but was %v", got)
	}
}

func Test_S01_CircleArea(t *testing.T) {
	if got := CircleArea(3); math.Abs(got-9*math.Pi) > 1e-9 {
		t.Fatalf("expected %v but was %v", 9*math.Pi, got)
	}
}

func Test_S02_Triangles(t *testing.T) {
	t.Run("S02 perimeter", func(t *testing.T) {
		if got := TrianglePerimeter(3, 4, 5); got != 12 {
			t.Fatalf("expected 12 but was %v", got)
		}
	})
	t.Run("S02 rejects impossible triangles", func(t *testing.T) {
		if IsValidTriangle(1, 2, 10) {
			t.Fatal("1, 2, 10 is not a triangle")
		}
	})
}

func TestVersion(t *testing.T) {
	if Version == "" {
		t.Fatal("empty version")
	}
}
