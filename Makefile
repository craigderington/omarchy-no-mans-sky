.PHONY: shaders check install uninstall
shaders:
	/usr/lib/qt6/bin/qsb --qt6 -o quickshell/land/land.frag.qsb quickshell/land/land.frag
	/usr/lib/qt6/bin/qsb --qt6 -o quickshell/starmap/starmap.frag.qsb quickshell/starmap/starmap.frag
	/usr/lib/qt6/bin/qsb --qt6 -o quickshell/common/orb.frag.qsb quickshell/common/orb.frag
check:
	python3 -m unittest discover -s tests -v
install:
	./bin/omarchy-nms install
uninstall:
	./bin/omarchy-nms uninstall
