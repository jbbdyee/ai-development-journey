import cv2

img = cv2.imread("cute.png")

print(img.shape)

resized = cv2.resize(img, (200, 300))

print(resized.shape)

cv2.imshow("Original", img)
cv2.imshow("Resized", resized)

cv2.waitKey(0)
cv2.destroyAllWindows()