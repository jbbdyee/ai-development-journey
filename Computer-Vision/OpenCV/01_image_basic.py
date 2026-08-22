import cv2

img = cv2.imread("cute.png")

print(type(img))
print(img.shape)
print(img[0, 0])

img_alpha = cv2.imread("cute.png", cv2.IMREAD_UNCHANGED)

print(img_alpha.shape)
print(img_alpha[0, 0])

cv2.imshow("My Image", img)

cv2.waitKey(0)
cv2.destroyAllWindows()